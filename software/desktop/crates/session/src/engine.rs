//! The engine process: `sight-engine` started as a child, spoken to over stdin/stdout.
//!
//! The command is `$LYNX_SIGHT_ENGINE` if set (split on whitespace), otherwise
//! `uv run --project <repo>/software/diagnostic sight-engine`. If it cannot start, the error
//! says so and the app runs without tracking instead of failing.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::thread;
use std::time::Duration;

use lynx_sight_contracts::engine::{Capabilities, Envelope, ErrorCode, Request, Response};
use lynx_sight_contracts::ENGINE_PROTOCOL_VERSION;

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("the engine could not be started ({command}): {reason}")]
    Unavailable { command: String, reason: String },
    #[error("the engine stopped: {0}")]
    Exited(String),
    #[error("no answer from the engine within {0:?}")]
    Timeout(Duration),
    #[error("engine protocol violation: {0}")]
    Protocol(String),
    #[error("engine refused ({code:?}): {message}")]
    Remote { code: ErrorCode, message: String },
}

pub type Result<T> = std::result::Result<T, EngineError>;

/// How to start the engine.
#[derive(Debug, Clone)]
pub struct EngineCommand {
    pub program: String,
    pub args: Vec<String>,
}

impl EngineCommand {
    pub fn from_env() -> EngineCommand {
        if let Ok(cmd) = std::env::var("LYNX_SIGHT_ENGINE") {
            let mut parts = cmd.split_whitespace().map(str::to_string);
            if let Some(program) = parts.next() {
                return EngineCommand {
                    program,
                    args: parts.collect(),
                };
            }
        }
        let project = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../diagnostic");
        EngineCommand {
            program: "uv".into(),
            args: vec![
                "run".into(),
                "--quiet".into(),
                "--project".into(),
                project.display().to_string(),
                "sight-engine".into(),
            ],
        }
    }

    fn describe(&self) -> String {
        std::iter::once(self.program.as_str())
            .chain(self.args.iter().map(String::as_str))
            .collect::<Vec<_>>()
            .join(" ")
    }
}

pub struct Engine {
    child: Child,
    stdin: ChildStdin,
    lines: Receiver<std::io::Result<String>>,
    next_id: u64,
    pub engine_version: String,
    pub capabilities: Capabilities,
    pub timeout: Duration,
}

impl Engine {
    /// Starts the engine and checks its protocol version with `hello`.
    pub fn start(command: &EngineCommand) -> Result<Engine> {
        let mut child = Command::new(&command.program)
            .args(&command.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| EngineError::Unavailable {
                command: command.describe(),
                reason: e.to_string(),
            })?;
        let stdin = child.stdin.take().expect("piped stdin");
        let stdout = child.stdout.take().expect("piped stdout");
        let (tx, rx) = mpsc::channel();
        thread::Builder::new()
            .name("engine-stdout".into())
            .spawn(move || {
                for line in BufReader::new(stdout).lines() {
                    if tx.send(line).is_err() {
                        break;
                    }
                }
            })
            .map_err(|e| EngineError::Unavailable {
                command: command.describe(),
                reason: e.to_string(),
            })?;
        let mut engine = Engine {
            child,
            stdin,
            lines: rx,
            next_id: 0,
            engine_version: String::new(),
            capabilities: Capabilities {
                cameras: false,
                landmarks: false,
                feature_sets: vec![],
                model_kinds: vec![],
            },
            // The first request may wait for `uv` to build the environment.
            timeout: Duration::from_secs(300),
        };
        match engine.request(Request::Hello {
            client: format!("lynx-sight-desktop {}", crate::APP_VERSION),
        }) {
            Ok(Response::Hello {
                engine_version,
                capabilities,
            }) => {
                engine.engine_version = engine_version;
                engine.capabilities = capabilities;
                engine.timeout = Duration::from_secs(60);
                Ok(engine)
            }
            Ok(other) => Err(EngineError::Protocol(format!(
                "expected hello, got {other:?}"
            ))),
            Err(EngineError::Exited(reason)) => Err(EngineError::Unavailable {
                command: command.describe(),
                reason,
            }),
            Err(e) => Err(e),
        }
    }

    /// Sends one request and waits for its response. Engine-side errors become
    /// [`EngineError::Remote`].
    pub fn request(&mut self, body: Request) -> Result<Response> {
        self.next_id += 1;
        let id = self.next_id;
        let envelope = Envelope {
            protocol: ENGINE_PROTOCOL_VERSION,
            id,
            body,
        };
        let mut line =
            serde_json::to_string(&envelope).map_err(|e| EngineError::Protocol(e.to_string()))?;
        line.push('\n');
        self.stdin
            .write_all(line.as_bytes())
            .and_then(|_| self.stdin.flush())
            .map_err(|e| EngineError::Exited(e.to_string()))?;
        let text = match self.lines.recv_timeout(self.timeout) {
            Ok(Ok(text)) => text,
            Ok(Err(e)) => return Err(EngineError::Exited(e.to_string())),
            Err(RecvTimeoutError::Timeout) => return Err(EngineError::Timeout(self.timeout)),
            Err(RecvTimeoutError::Disconnected) => {
                let status = self.child.try_wait().ok().flatten();
                return Err(EngineError::Exited(format!(
                    "output closed (exit status {status:?})"
                )));
            }
        };
        let reply: Envelope<Response> = serde_json::from_str(&text)
            .map_err(|e| EngineError::Protocol(format!("{e}: {text}")))?;
        if reply.protocol != ENGINE_PROTOCOL_VERSION {
            return Err(EngineError::Protocol(format!(
                "engine answered with protocol {}",
                reply.protocol
            )));
        }
        if reply.id != id {
            return Err(EngineError::Protocol(format!(
                "answer {} to request {id}",
                reply.id
            )));
        }
        match reply.body {
            Response::Error { code, message } => Err(EngineError::Remote { code, message }),
            body => Ok(body),
        }
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        self.timeout = Duration::from_secs(5);
        let _ = self.request(Request::Shutdown);
        if !matches!(self.child.try_wait(), Ok(Some(_))) {
            thread::sleep(Duration::from_millis(200));
            let _ = self.child.kill();
        }
        let _ = self.child.wait();
    }
}

/// Unwraps the expected response variant, or reports a protocol violation.
#[macro_export]
macro_rules! expect_response {
    ($response:expr, $variant:ident { $($field:ident),* }) => {
        match $response {
            lynx_sight_contracts::engine::Response::$variant { $($field),* } => Ok(($($field),*)),
            other => Err($crate::engine::EngineError::Protocol(format!(
                concat!("expected ", stringify!($variant), ", got {:?}"), other
            ))),
        }
    };
}
