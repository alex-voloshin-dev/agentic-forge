<?php

declare(strict_types=1);

namespace Example;

use InvalidArgumentException;

final class Ports
{
    /** Parse $text as a TCP port in the range 1-65535. */
    public static function parsePort(string $text): int
    {
        $trimmed = trim($text);
        if (!ctype_digit($trimmed)) {
            throw new InvalidArgumentException(sprintf('not a port: %s', $text));
        }
        $value = (int) $trimmed;
        if ($value < 1 || $value > 65535) {
            throw new InvalidArgumentException(sprintf('port out of range: %d', $value));
        }

        return $value;
    }
}
