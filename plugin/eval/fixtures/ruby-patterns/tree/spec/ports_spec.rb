# frozen_string_literal: true

require_relative "../lib/ports"

RSpec.describe Ports do
  it "accepts a registered port" do
    expect(described_class.parse_port("8080")).to eq(8080)
  end

  it "rejects garbage and out-of-range values" do
    expect { described_class.parse_port("http") }.to raise_error(Ports::Error)
    expect { described_class.parse_port("70000") }.to raise_error(Ports::Error)
  end
end
