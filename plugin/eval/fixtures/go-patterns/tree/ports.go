// Package ports parses and validates TCP port numbers.
package ports

import (
	"fmt"
	"strconv"
	"strings"
)

// ParsePort parses text as a TCP port in the range 1-65535.
func ParsePort(text string) (int, error) {
	value, err := strconv.Atoi(strings.TrimSpace(text))
	if err != nil {
		return 0, fmt.Errorf("not a port %q: %w", text, err)
	}
	if value < 1 || value > 65535 {
		return 0, fmt.Errorf("port out of range: %d", value)
	}
	return value, nil
}
