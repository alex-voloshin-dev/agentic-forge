# frozen_string_literal: true

# Port parsing helpers.
module Ports
  class Error < StandardError; end

  RANGE = (1..65_535)

  # Parse +text+ as a TCP port in the range 1-65535.
  def self.parse_port(text)
    trimmed = text.to_s.strip
    raise Error, "not a port: #{text.inspect}" unless trimmed.match?(/\A\d+\z/)

    value = Integer(trimmed, 10)
    raise Error, "port out of range: #{value}" unless RANGE.cover?(value)

    value
  end
end
