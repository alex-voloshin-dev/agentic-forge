<?php

declare(strict_types=1);

namespace Example\Tests;

use Example\Ports;
use InvalidArgumentException;
use PHPUnit\Framework\TestCase;

final class PortsTest extends TestCase
{
    public function testAcceptsARegisteredPort(): void
    {
        self::assertSame(8080, Ports::parsePort('8080'));
    }

    public function testRejectsGarbage(): void
    {
        $this->expectException(InvalidArgumentException::class);
        Ports::parsePort('http');
    }

    public function testRejectsOutOfRange(): void
    {
        $this->expectException(InvalidArgumentException::class);
        Ports::parsePort('70000');
    }
}
