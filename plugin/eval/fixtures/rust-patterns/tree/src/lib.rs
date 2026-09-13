//! Port parsing helpers.

use std::fmt;

#[derive(Debug, PartialEq, Eq)]
pub enum PortError {
    NotANumber(String),
    OutOfRange(u32),
}

impl fmt::Display for PortError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PortError::NotANumber(text) => write!(f, "not a port: {text:?}"),
            PortError::OutOfRange(value) => write!(f, "port out of range: {value}"),
        }
    }
}

impl std::error::Error for PortError {}

/// Parse `text` as a TCP port in the range 1..=65535.
pub fn parse_port(text: &str) -> Result<u16, PortError> {
    let value: u32 = text
        .trim()
        .parse()
        .map_err(|_| PortError::NotANumber(text.to_owned()))?;
    if value == 0 || value > u32::from(u16::MAX) {
        return Err(PortError::OutOfRange(value));
    }
    Ok(value as u16)
}
