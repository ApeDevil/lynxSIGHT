//! Display geometry: what displays exist, where they are, and how points move between the
//! coordinate systems defined in `docs/architecture/coordinate-systems.md`.
//!
//! Every transform is a pure function over contract types ([`transform`], [`rig`]); discovery
//! ([`discovery`]) gathers platform facts behind small traits so other platforms can be added
//! without another geometry model.

pub mod discovery;
pub mod edid;
pub mod rig;
pub mod transform;
pub mod vec3;

pub use transform::*;
