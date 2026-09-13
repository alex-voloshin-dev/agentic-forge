using Xunit;

namespace Ports.Tests;

public class PortParserTests
{
    [Fact]
    public void AcceptsARegisteredPort()
    {
        Assert.Equal(8080, PortParser.Parse("8080"));
    }

    [Fact]
    public void RejectsGarbageAndOutOfRange()
    {
        Assert.Throws<ArgumentException>(() => PortParser.Parse("http"));
        Assert.Throws<ArgumentOutOfRangeException>(() => PortParser.Parse("70000"));
    }
}
