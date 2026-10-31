//! Parsing of the 128-byte EDID base block: identity, physical size and preferred mode.
//!
//! EDID sizes are estimates: many panels report rounded centimetres, projectors and some TVs
//! report 0 or an aspect ratio, and adapters may invent values. Every size parsed here is
//! marked [`Provenance::Edid`] so the user can correct it.

use lynx_sight_contracts::display::{PhysicalSize, PixelSize};
use lynx_sight_contracts::metric::Provenance;

#[derive(Debug, Clone, PartialEq)]
pub struct EdidInfo {
    /// Three-letter PNP manufacturer ID, e.g. `DEL`.
    pub manufacturer: String,
    pub product_code: u16,
    /// Numeric serial from the header; 0 means none.
    pub serial_number: u32,
    /// From the monitor serial string descriptor, if present.
    pub serial_text: Option<String>,
    /// From the monitor name descriptor, if present.
    pub name: Option<String>,
    pub physical: Option<PhysicalSize>,
    pub preferred_mode: Option<PixelSize>,
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum EdidError {
    #[error("EDID shorter than 128 bytes ({0})")]
    TooShort(usize),
    #[error("EDID header missing")]
    BadHeader,
    #[error("EDID checksum mismatch")]
    BadChecksum,
}

const HEADER: [u8; 8] = [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00];

impl EdidInfo {
    /// `edid:<manufacturer>-<product code>-<serial>`, or None without any serial: identical
    /// monitors without serials cannot be told apart, and the connector must do.
    pub fn stable_id(&self) -> Option<String> {
        let serial = self
            .serial_text
            .clone()
            .or_else(|| (self.serial_number != 0).then(|| self.serial_number.to_string()))?;
        Some(format!(
            "edid:{}-{:04x}-{}",
            self.manufacturer, self.product_code, serial
        ))
    }
}

pub fn parse(bytes: &[u8]) -> Result<EdidInfo, EdidError> {
    if bytes.len() < 128 {
        return Err(EdidError::TooShort(bytes.len()));
    }
    let b = &bytes[..128];
    if b[..8] != HEADER {
        return Err(EdidError::BadHeader);
    }
    if b.iter().fold(0u8, |acc, v| acc.wrapping_add(*v)) != 0 {
        return Err(EdidError::BadChecksum);
    }
    let packed = u16::from_be_bytes([b[8], b[9]]);
    let letter = |shift: u16| char::from(b'A' - 1 + ((packed >> shift) & 0x1F) as u8);
    let manufacturer: String = [letter(10), letter(5), letter(0)].iter().collect();
    let product_code = u16::from_le_bytes([b[10], b[11]]);
    let serial_number = u32::from_le_bytes([b[12], b[13], b[14], b[15]]);

    let mut name = None;
    let mut serial_text = None;
    let mut preferred_mode = None;
    let mut dtd_size = None;
    for (i, d) in b[54..126].chunks_exact(18).enumerate() {
        let pixel_clock = u16::from_le_bytes([d[0], d[1]]);
        if pixel_clock != 0 {
            if i == 0 {
                let w = u32::from(d[2]) | (u32::from(d[4] >> 4) << 8);
                let h = u32::from(d[5]) | (u32::from(d[7] >> 4) << 8);
                preferred_mode = Some(PixelSize {
                    width: w,
                    height: h,
                });
                let wmm = u32::from(d[12]) | (u32::from(d[14] >> 4) << 8);
                let hmm = u32::from(d[13]) | (u32::from(d[14] & 0x0F) << 8);
                dtd_size = (wmm > 0 && hmm > 0).then_some((f64::from(wmm), f64::from(hmm)));
            }
            continue;
        }
        let text = || descriptor_text(&d[5..18]);
        match d[3] {
            0xFC => name = text(),
            0xFF => serial_text = text(),
            _ => {}
        }
    }
    // The detailed timing's millimetres are finer than the header's centimetres. A
    // centimetre pair may also be an aspect ratio when one of them is 0; then no size.
    let header_size =
        (b[21] > 0 && b[22] > 0).then(|| (f64::from(b[21]) * 10.0, f64::from(b[22]) * 10.0));
    let physical = dtd_size.or(header_size).map(|(w, h)| PhysicalSize {
        width_mm: w,
        height_mm: h,
        provenance: Provenance::Edid,
    });
    Ok(EdidInfo {
        manufacturer,
        product_code,
        serial_number,
        serial_text,
        name,
        physical,
        preferred_mode,
    })
}

fn descriptor_text(raw: &[u8]) -> Option<String> {
    let end = raw.iter().position(|c| *c == 0x0A).unwrap_or(raw.len());
    let s: String = raw[..end].iter().map(|c| char::from(*c)).collect();
    let s = s.trim().to_string();
    (!s.is_empty()).then_some(s)
}

/// Builds a valid EDID base block, for tests of everything that consumes EDIDs.
pub fn synthesize(
    manufacturer: &str,
    product_code: u16,
    serial: u32,
    name: &str,
    mode: (u32, u32),
    size_mm: (u32, u32),
) -> Vec<u8> {
    let mut b = vec![0u8; 128];
    b[..8].copy_from_slice(&HEADER);
    let m: Vec<u16> = manufacturer
        .bytes()
        .map(|c| u16::from(c - b'A' + 1))
        .collect();
    b[8..10].copy_from_slice(&((m[0] << 10) | (m[1] << 5) | m[2]).to_be_bytes());
    b[10..12].copy_from_slice(&product_code.to_le_bytes());
    b[12..16].copy_from_slice(&serial.to_le_bytes());
    b[18] = 1;
    b[19] = 4;
    b[21] = (size_mm.0 / 10) as u8;
    b[22] = (size_mm.1 / 10) as u8;
    let d = &mut b[54..72];
    d[0..2].copy_from_slice(&14850u16.to_le_bytes());
    d[2] = (mode.0 & 0xFF) as u8;
    d[4] = ((mode.0 >> 8) as u8) << 4;
    d[5] = (mode.1 & 0xFF) as u8;
    d[7] = ((mode.1 >> 8) as u8) << 4;
    d[12] = (size_mm.0 & 0xFF) as u8;
    d[13] = (size_mm.1 & 0xFF) as u8;
    d[14] = (((size_mm.0 >> 8) as u8) << 4) | ((size_mm.1 >> 8) as u8 & 0x0F);
    let n = &mut b[72..90];
    n[3] = 0xFC;
    let text: Vec<u8> = name
        .bytes()
        .chain(std::iter::once(0x0A))
        .chain(std::iter::repeat(0x20))
        .take(13)
        .collect();
    n[5..18].copy_from_slice(&text);
    let sum = b[..127].iter().fold(0u8, |acc, v| acc.wrapping_add(*v));
    b[127] = 0u8.wrapping_sub(sum);
    b
}
