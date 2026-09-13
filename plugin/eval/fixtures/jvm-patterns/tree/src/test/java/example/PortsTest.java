package example;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import org.junit.jupiter.api.Test;

class PortsTest {
    @Test
    void acceptsARegisteredPort() {
        assertEquals(8080, Ports.parsePort("8080"));
    }

    @Test
    void rejectsGarbageAndOutOfRange() {
        assertThrows(IllegalArgumentException.class, () -> Ports.parsePort("http"));
        assertThrows(IllegalArgumentException.class, () -> Ports.parsePort("70000"));
    }
}
