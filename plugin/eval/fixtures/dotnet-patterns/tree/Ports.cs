namespace Ports;

/// <summary>Port parsing helpers.</summary>
public static class PortParser
{
    /// <summary>Parses <paramref name="text"/> as a TCP port in the range 1-65535.</summary>
    public static int Parse(string text)
    {
        if (!int.TryParse(text.Trim(), out var value))
        {
            throw new ArgumentException($"not a port: {text}", nameof(text));
        }
        if (value is < 1 or > 65535)
        {
            throw new ArgumentOutOfRangeException(nameof(text), value, "port out of range");
        }
        return value;
    }
}
