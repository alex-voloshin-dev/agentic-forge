package ports

import "testing"

func TestParsePort(t *testing.T) {
	cases := []struct {
		name    string
		in      string
		want    int
		wantErr bool
	}{
		{"registered port", "8080", 8080, false},
		{"garbage", "http", 0, true},
		{"out of range", "70000", 0, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := ParsePort(tc.in)
			if (err != nil) != tc.wantErr {
				t.Fatalf("ParsePort(%q) error = %v, wantErr %v", tc.in, err, tc.wantErr)
			}
			if got != tc.want {
				t.Fatalf("ParsePort(%q) = %d, want %d", tc.in, got, tc.want)
			}
		})
	}
}
