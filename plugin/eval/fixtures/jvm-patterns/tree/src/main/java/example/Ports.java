package example;

/** Port parsing helpers. */
public final class Ports {
    private Ports() {}

    /** Parses {@code text} as a TCP port in the range 1-65535. */
    public static int parsePort(String text) {
        final int value;
        try {
            value = Integer.parseInt(text.trim());
        } catch (NumberFormatException e) {
            throw new IllegalArgumentException("not a port: " + text, e);
        }
        if (value < 1 || value > 65535) {
            throw new IllegalArgumentException("port out of range: " + value);
        }
        return value;
    }
}
