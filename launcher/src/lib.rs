//! Launcher for Spark Desktop on aarch64 Linux.
//!
//! Spark is an x86_64 Windows application. On an ARM host it runs as
//! muvm (4K-page microVM) -> FEX-Emu -> Wine -> Spark. The pure logic lives
//! here so tests can call it; `main.rs` does the process and file work.

pub mod desktop;
pub mod inspect;
pub mod links;
pub mod vm;
