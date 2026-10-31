//! The calibration workflows as explicit step lists, and the session that walks them.
//!
//! * **Full:** face baseline (three stages) → stationary targets → two pursuit paths →
//!   independent validation targets → fit → review.
//! * **Quick:** a few stationary targets → validation targets → correction of the active model
//!   → review. Needs a profile with an active model fitted on the same feature set.
//! * **Incremental:** no steps; [`CalibrationSession::propose_correction`] takes trusted
//!   observations and yields a candidate for review, like the others.
//!
//! Every candidate ends in review: [`crate::acceptance`] decides whether it may be installed
//! directly or needs the user's confirmation, and the previous model stays in the history.
//! Steps can be restarted or (collect steps) skipped; dropping the session cancels it.

use lynx_sight_contracts::app::{Acceptance, Candidate, SessionView, Step, StepRecord};
use lynx_sight_contracts::calibration::{
    CollectionSummary, GazeModel, MetricScale, PlanRequest, Presentation, Purpose,
    StationaryLayout, TargetPlan, TimeSpan, Trajectory, TrustedObservation,
};
use lynx_sight_contracts::engine::{Request, SourceSpec};
use lynx_sight_contracts::metric::Metric;
use lynx_sight_contracts::profile::{
    CalibrationRecord, Environment, Profile, RecordStatus, Workflow,
};
use lynx_sight_contracts::tracking::{
    BaselineStage, BaselineStageResult, FaceBaseline, TrackingStatus,
};
use lynx_sight_profile::{history, new_id, now_rfc3339, ProfileStore};

use crate::acceptance;
use crate::engine::{Engine, EngineError};
use crate::expect_response;

#[derive(Debug, thiserror::Error)]
pub enum SessionError {
    #[error(transparent)]
    Engine(#[from] EngineError),
    #[error(transparent)]
    Profile(#[from] lynx_sight_profile::ProfileError),
    #[error("{0}")]
    Step(String),
}

pub type Result<T> = std::result::Result<T, SessionError>;

fn step_err<T>(msg: impl Into<String>) -> Result<T> {
    Err(SessionError::Step(msg.into()))
}

/// Comfortable defaults; all provisional until tuned on the real setup.
pub fn full_steps(aspect: f64) -> Vec<Step> {
    let baseline = [
        BaselineStage::DetectStable,
        BaselineStage::Neutral,
        BaselineStage::PoseRange,
    ];
    let mut steps: Vec<Step> = baseline
        .into_iter()
        .map(|stage| Step::Baseline { stage })
        .collect();
    steps.push(Step::Collect {
        label: "Stationary targets: centre, edges and corners".into(),
        request: PlanRequest::Stationary {
            purpose: Purpose::Fit,
            layout: StationaryLayout::CentreEdgesCorners { margin: 0.05 },
            settle_ms: 700,
            dwell_ms: 1200,
            aspect,
        },
    });
    steps.push(Step::Collect {
        label: "Follow the moving target: spiral".into(),
        request: PlanRequest::Pursuit {
            purpose: Purpose::Fit,
            trajectory: Trajectory::Spiral {
                turns: 3.0,
                margin: 0.06,
            },
            speed: 0.2,
            lead_in_ms: 1000,
            aspect,
        },
    });
    steps.push(Step::Collect {
        label: "Follow the moving target: along the edges".into(),
        request: PlanRequest::Pursuit {
            purpose: Purpose::Fit,
            trajectory: Trajectory::Perimeter { margin: 0.05 },
            speed: 0.25,
            lead_in_ms: 1000,
            aspect,
        },
    });
    steps.push(validation_step(4, 3, 0.06, aspect));
    steps.push(Step::Fit);
    steps.push(Step::Review);
    steps
}

pub fn quick_steps(aspect: f64) -> Vec<Step> {
    vec![
        Step::Collect {
            label: "Quick targets".into(),
            request: PlanRequest::Stationary {
                purpose: Purpose::Fit,
                layout: StationaryLayout::CentreEdgesCorners { margin: 0.1 },
                settle_ms: 600,
                dwell_ms: 900,
                aspect,
            },
        },
        validation_step(3, 3, 0.1, aspect),
        Step::Recalibrate,
        Step::Review,
    ]
}

fn validation_step(cols: u32, rows: u32, margin: f64, aspect: f64) -> Step {
    Step::Collect {
        label: "Validation targets (not used for fitting)".into(),
        request: PlanRequest::Stationary {
            purpose: Purpose::Validation,
            layout: StationaryLayout::ValidationOffsetGrid { cols, rows, margin },
            settle_ms: 700,
            dwell_ms: 1000,
            aspect,
        },
    }
}

struct Pending {
    candidate: Candidate,
    model: GazeModel,
    collections: Vec<CollectionSummary>,
    environment: Environment,
}

pub struct CalibrationSession {
    engine: Engine,
    pub profile: Profile,
    workflow: Workflow,
    steps: Vec<StepRecord>,
    current: usize,
    plan: Option<TargetPlan>,
    baseline: Option<FaceBaseline>,
    pending: Option<Pending>,
    scale: MetricScale,
    message: Option<String>,
    pub synthetic: bool,
    pub feature_set: String,
    /// The engine's time origin; simulated runs place their presentations after it.
    pub clock_origin_ns: i64,
}

impl CalibrationSession {
    pub fn start(
        mut engine: Engine,
        source: SourceSpec,
        profile: Profile,
        workflow: Workflow,
    ) -> Result<Self> {
        let (_cameras, synthetic, clock_origin_ns, feature_set) = expect_response!(
            engine.request(Request::OpenSource { source })?,
            SourceOpened {
                cameras,
                synthetic,
                clock_origin_ns,
                feature_set
            }
        )?;
        let scale = lynx_sight_geometry::metric_scale(&profile.display);
        let aspect = f64::from(scale.width_px) / f64::from(scale.height_px);
        let steps = match workflow {
            Workflow::Full => full_steps(aspect),
            Workflow::Quick => {
                let Some(active) = &profile.active else {
                    return step_err(
                        "quick recalibration needs a profile with an active calibration",
                    );
                };
                if active.model.feature_set != feature_set {
                    return step_err(format!(
                        "the active model uses {}, the engine delivers {}: run a full calibration",
                        active.model.feature_set, feature_set
                    ));
                }
                quick_steps(aspect)
            }
            Workflow::Incremental => vec![Step::Review],
        };
        let steps = steps
            .into_iter()
            .map(|step| StepRecord {
                step,
                done: false,
                skipped: false,
                baseline: None,
                collection: None,
            })
            .collect();
        Ok(CalibrationSession {
            engine,
            profile,
            workflow,
            steps,
            current: 0,
            plan: None,
            baseline: None,
            pending: None,
            scale,
            message: None,
            synthetic,
            feature_set,
            clock_origin_ns,
        })
    }

    pub fn view(&self) -> SessionView {
        SessionView {
            workflow: self.workflow,
            profile_id: self.profile.profile_id.clone(),
            synthetic: self.synthetic,
            feature_set: self.feature_set.clone(),
            steps: self.steps.clone(),
            current: self.current as u32,
            plan: self.plan.clone(),
            baseline: self.baseline.clone(),
            candidate: self.pending.as_ref().map(|p| p.candidate.clone()),
            message: self.message.clone(),
        }
    }

    pub fn current_step(&self) -> Option<&Step> {
        self.steps.get(self.current).map(|r| &r.step)
    }

    pub fn finished(&self) -> bool {
        self.current >= self.steps.len()
    }

    pub fn tracking_status(&mut self) -> Result<TrackingStatus> {
        Ok(expect_response!(
            self.engine.request(Request::TrackingStatus)?,
            TrackingStatus { status }
        )?)
    }

    fn advance(&mut self) {
        self.steps[self.current].done = true;
        self.current += 1;
        self.plan = None;
    }

    pub fn capture_baseline(&mut self, span: TimeSpan) -> Result<BaselineStageResult> {
        let Some(Step::Baseline { stage }) = self.current_step().cloned() else {
            return step_err("the current step is not a baseline stage");
        };
        let result = expect_response!(
            self.engine
                .request(Request::CaptureBaselineStage { stage, span })?,
            BaselineStage { result }
        )?;
        self.steps[self.current].baseline = Some(result.clone());
        if !result.ok {
            self.message = Some(result.message.clone());
            return Ok(result);
        }
        self.message = None;
        let last = !matches!(
            self.steps.get(self.current + 1).map(|r| &r.step),
            Some(Step::Baseline { .. })
        );
        if last {
            let baseline = expect_response!(
                self.engine.request(Request::FinishBaseline)?,
                Baseline { baseline }
            )?;
            self.baseline = Some(baseline);
        }
        self.advance();
        Ok(result)
    }

    pub fn plan(&mut self) -> Result<TargetPlan> {
        let Some(Step::Collect { request, .. }) = self.current_step().cloned() else {
            return step_err("the current step does not show targets");
        };
        let plan = expect_response!(
            self.engine.request(Request::Plan { request })?,
            Plan { plan }
        )?;
        self.plan = Some(plan.clone());
        Ok(plan)
    }

    pub fn submit(&mut self, presentation: Presentation) -> Result<CollectionSummary> {
        let Some(plan) = &self.plan else {
            return step_err("no plan is being presented");
        };
        if plan.plan_id != presentation.plan_id {
            return step_err(format!(
                "presentation of {} while {} is current",
                presentation.plan_id, plan.plan_id
            ));
        }
        let summary = expect_response!(
            self.engine
                .request(Request::SubmitPresentation { presentation })?,
            Collection { summary }
        )?;
        self.message = (!summary.warnings.is_empty()).then(|| summary.warnings.join("; "));
        self.steps[self.current].collection = Some(summary.clone());
        self.advance();
        Ok(summary)
    }

    /// Discards the current step's data and starts it again.
    pub fn restart_step(&mut self) {
        if let Some(r) = self.steps.get_mut(self.current) {
            r.collection = None;
            r.baseline = None;
        }
        self.plan = None;
    }

    /// Moves back to the previous collect step to redo it (e.g. after a poor collection).
    pub fn redo(&mut self, index: usize) -> Result<()> {
        if index >= self.current
            || !matches!(
                self.steps[index].step,
                Step::Collect { .. } | Step::Baseline { .. }
            )
        {
            return step_err("only completed baseline or target steps can be redone");
        }
        for r in &mut self.steps[index..] {
            *r = StepRecord {
                step: r.step.clone(),
                done: false,
                skipped: false,
                baseline: None,
                collection: None,
            };
        }
        self.current = index;
        self.plan = None;
        self.pending = None;
        Ok(())
    }

    pub fn skip_step(&mut self) -> Result<()> {
        match self.current_step() {
            Some(Step::Collect { .. }) => {
                self.steps[self.current].skipped = true;
                self.advance();
                Ok(())
            }
            _ => step_err("only target steps can be skipped"),
        }
    }

    fn collected(&self, purpose: Purpose) -> Vec<String> {
        self.steps
            .iter()
            .filter_map(|r| r.collection.as_ref())
            .filter(|c| c.purpose == purpose)
            .map(|c| c.plan_id.clone())
            .collect()
    }

    /// Fits (full) or corrects (quick) the model, compares it with the active one, and moves
    /// to review.
    pub fn run_model_step(&mut self) -> Result<&Candidate> {
        let fit_plans = self.collected(Purpose::Fit);
        let validation_plans = self.collected(Purpose::Validation);
        let active = self.profile.active.as_ref().map(|a| a.model.clone());
        let scale = self.scale;
        let (fit, model, comparison) = match self.current_step() {
            Some(Step::Fit) => {
                let result = expect_response!(
                    self.engine.request(Request::Fit {
                        fit_plans,
                        validation_plans: validation_plans.clone(),
                        scale
                    })?,
                    Fit { result }
                )?;
                let comparison = match &active {
                    Some(current)
                        if current.feature_set == result.model.feature_set
                            && !validation_plans.is_empty() =>
                    {
                        let compared = self.engine.request(Request::Compare {
                            current: current.clone(),
                            candidate: result.model.clone(),
                            validation_plans,
                            scale,
                        });
                        match compared {
                            Ok(r) => Some(expect_response!(r, Comparison { comparison })?),
                            // An old model the engine cannot read: nothing to compare with.
                            Err(EngineError::Remote { .. }) => None,
                            Err(e) => return Err(e.into()),
                        }
                    }
                    _ => None,
                };
                let model = result.model.clone();
                (Some(result), model, comparison)
            }
            Some(Step::Recalibrate) => {
                let Some(current) = active.clone() else {
                    return step_err("no active model to correct");
                };
                let result = expect_response!(
                    self.engine.request(Request::Recalibrate {
                        current,
                        fit_plans,
                        validation_plans,
                        scale
                    })?,
                    Recalibration { result }
                )?;
                (None, result.candidate, Some(result.comparison))
            }
            _ => return step_err("the current step does not fit a model"),
        };
        let validation = match (&fit, &comparison) {
            (Some(f), _) => f.validation.clone(),
            (None, Some(c)) => c.candidate.clone(),
            (None, None) => unreachable!("recalibration always compares"),
        };
        let acceptance = acceptance::decide(&validation, comparison.as_ref(), active.is_some());
        let level = self
            .tracking_status()
            .map(|t| t.mean_image_level)
            .unwrap_or(Metric::unavailable("no tracking status"));
        let environment = Environment {
            camera_modes: vec![if self.synthetic {
                "synthetic".into()
            } else {
                "cameras".into()
            }],
            mean_image_level: level,
            background_brightness: None,
            notes: String::new(),
        };
        let collections = self
            .steps
            .iter()
            .filter_map(|r| r.collection.clone())
            .collect();
        self.pending = Some(Pending {
            candidate: Candidate {
                workflow: self.workflow,
                fit,
                validation,
                comparison,
                acceptance,
            },
            model,
            collections,
            environment,
        });
        self.advance();
        Ok(&self.pending.as_ref().expect("just set").candidate)
    }

    /// Incremental correction from trusted observations; the result goes to review.
    pub fn propose_correction(
        &mut self,
        observations: Vec<TrustedObservation>,
        validation_plans: Vec<String>,
    ) -> Result<Option<&Candidate>> {
        let Some(current) = self.profile.active.as_ref().map(|a| a.model.clone()) else {
            return step_err("no active model to correct");
        };
        let proposal = expect_response!(
            self.engine.request(Request::ProposeCorrection {
                current: current.clone(),
                observations
            })?,
            CorrectionProposal { proposal }
        )?;
        let Some(candidate) = proposal.candidate else {
            self.message = Some(proposal.reason);
            return Ok(None);
        };
        let comparison = expect_response!(
            self.engine.request(Request::Compare {
                current,
                candidate: candidate.clone(),
                validation_plans,
                scale: self.scale
            })?,
            Comparison { comparison }
        )?;
        let validation = comparison.candidate.clone();
        let acceptance = acceptance::decide(&validation, Some(&comparison), true);
        self.pending = Some(Pending {
            candidate: Candidate {
                workflow: Workflow::Incremental,
                fit: None,
                validation,
                comparison: Some(comparison),
                acceptance,
            },
            model: candidate,
            collections: vec![],
            environment: Environment {
                camera_modes: vec![],
                mean_image_level: Metric::unavailable("not measured"),
                background_brightness: None,
                notes: proposal.reason,
            },
        });
        Ok(self.pending.as_ref().map(|p| &p.candidate))
    }

    pub fn set_background_brightness(&mut self, brightness: f64) {
        if let Some(p) = &mut self.pending {
            p.environment.background_brightness = Some(brightness);
        }
    }

    /// Installs the candidate. Without `confirmed`, only candidates the policy allows directly.
    pub fn accept(&mut self, store: &ProfileStore, confirmed: bool) -> Result<()> {
        let Some(pending) = self.pending.take() else {
            return step_err("nothing to accept");
        };
        if let Acceptance::ConfirmFirst { reason } = &pending.candidate.acceptance {
            if !confirmed {
                let reason = reason.clone();
                self.pending = Some(pending);
                return step_err(format!("needs confirmation: {reason}"));
            }
        }
        let record = self.record(pending, RecordStatus::Active);
        if self.workflow == Workflow::Full {
            if let Some(b) = self.baseline.clone() {
                self.profile.face_baseline = Some(b);
            }
        }
        history::install_active(&mut self.profile, record);
        store.save(&self.profile)?;
        self.finish_review();
        Ok(())
    }

    /// Keeps the active model; the candidate is stored as rejected, for comparison later.
    pub fn decline(&mut self, store: &ProfileStore) -> Result<()> {
        let Some(pending) = self.pending.take() else {
            return step_err("nothing to decline");
        };
        let record = self.record(pending, RecordStatus::Rejected);
        history::add_rejected(&mut self.profile, record);
        store.save(&self.profile)?;
        self.finish_review();
        Ok(())
    }

    fn finish_review(&mut self) {
        if matches!(self.current_step(), Some(Step::Review)) {
            self.advance();
        }
    }

    fn record(&self, pending: Pending, status: RecordStatus) -> CalibrationRecord {
        let coverage = pending
            .candidate
            .fit
            .as_ref()
            .and_then(|f| f.coverage.clone())
            .or_else(|| {
                // A correction keeps the fitted model's coverage.
                self.profile
                    .active
                    .as_ref()
                    .and_then(|a| a.coverage.clone())
            });
        CalibrationRecord {
            record_id: new_id(),
            workflow: pending.candidate.workflow,
            status,
            created_at: now_rfc3339(),
            model: pending.model,
            training: pending.candidate.fit.as_ref().map(|f| f.training.clone()),
            validation: pending.candidate.validation,
            collections: pending.collections,
            coverage,
            environment: pending.environment,
        }
    }

    /// Runs the current step with the simulated presenter at simulated time `t_ns` (after
    /// [`Self::clock_origin_ns`]) and returns the time after it. Review is left to the caller.
    pub fn simulate_step(&mut self, t_ns: i64) -> Result<i64> {
        const GAP_NS: i64 = 500_000_000;
        match self.current_step().cloned() {
            Some(Step::Baseline { .. }) => {
                let span = TimeSpan {
                    start_ns: t_ns,
                    end_ns: t_ns + 3_000_000_000,
                };
                let r = self.capture_baseline(span)?;
                if !r.ok {
                    return step_err(format!("baseline stage failed: {}", r.message));
                }
                Ok(span.end_ns + GAP_NS)
            }
            Some(Step::Collect { .. }) => {
                let plan = self.plan()?;
                let (presentation, end) = crate::presenter::simulate(&plan, t_ns);
                self.submit(presentation)?;
                Ok(end + GAP_NS)
            }
            Some(Step::Fit | Step::Recalibrate) => {
                self.run_model_step()?;
                Ok(t_ns)
            }
            Some(Step::Review) | None => step_err("nothing to simulate"),
        }
    }

    /// Simulates every remaining step up to review.
    pub fn simulate_until_review(&mut self, mut t_ns: i64) -> Result<i64> {
        while !matches!(self.current_step(), Some(Step::Review) | None) {
            t_ns = self.simulate_step(t_ns)?;
        }
        Ok(t_ns)
    }
}

/// A new, empty profile for `display`.
pub fn new_profile(
    name: &str,
    display: lynx_sight_contracts::display::DisplayCalibration,
    rig: lynx_sight_contracts::profile::RigConfig,
    engine_version: Option<String>,
) -> Profile {
    let now = now_rfc3339();
    Profile {
        schema: lynx_sight_contracts::PROFILE_SCHEMA_ID.into(),
        schema_version: lynx_sight_contracts::PROFILE_SCHEMA_VERSION,
        profile_id: new_id(),
        name: name.trim().to_string(),
        created_at: now.clone(),
        updated_at: now,
        software: lynx_sight_contracts::profile::SoftwareInfo {
            app_version: crate::APP_VERSION.into(),
            engine_version,
            engine_protocol: lynx_sight_contracts::ENGINE_PROTOCOL_VERSION,
        },
        rig,
        display,
        face_baseline: None,
        active: None,
        history: vec![],
    }
}
