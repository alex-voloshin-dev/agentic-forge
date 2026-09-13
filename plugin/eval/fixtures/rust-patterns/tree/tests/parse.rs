use ports::{parse_port, PortError};

#[test]
fn accepts_a_registered_port() {
    assert_eq!(parse_port("8080"), Ok(8080));
}

#[test]
fn rejects_garbage_and_out_of_range() {
    assert!(matches!(parse_port("http"), Err(PortError::NotANumber(_))));
    assert_eq!(parse_port("70000"), Err(PortError::OutOfRange(70000)));
}
