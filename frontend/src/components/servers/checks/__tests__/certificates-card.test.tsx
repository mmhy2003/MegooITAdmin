import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CertificatesCard } from "@/components/servers/checks/certificates-card";
import { formatTime } from "@/components/profile/profile-page";
import type { Certificate, ServerCheck } from "@/lib/checks";

const now = new Date("2026-11-25T12:00:00Z");

function cert(port: number, days: number): Certificate {
  return {
    port,
    subject: `CN=site${port}.example.com`,
    issuer: "CN=Example CA",
    not_after: new Date(now.getTime() + days * 86_400_000).toISOString(),
    fingerprint_sha256: "AB:CD",
  };
}

function check(certificates: Certificate[]): ServerCheck<"certificates"> {
  return {
    kind: "certificates",
    status: "ok",
    checked_at: "2026-11-25T10:00:00Z",
    every_seconds: 21600,
    data: { certificates },
    data_at: "2026-11-25T10:00:00Z",
  };
}

describe("CertificatesCard", () => {
  it("shows each certificate with its port, names, expiry and tone", () => {
    const certificates = [cert(443, -1), cert(8443, 3), cert(993, 10), cert(995, 40)];
    render(<CertificatesCard check={check(certificates)} now={now} />);
    expect(screen.getByRole("heading", { level: 3, name: "Certificates" })).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    const expected: [string, string][] = [
      ["Expired", "text-pink-ink"],
      ["Expires in 3 days", "text-pink-ink"],
      ["Expires in 10 days", "text-amber-ink"],
      ["Valid", "text-green-ink"],
    ];
    rows.forEach((row, i) => {
      const item = certificates[i];
      expect(within(row).getByText(`Port ${item.port}`)).toBeInTheDocument();
      expect(within(row).getByText(item.subject)).toBeInTheDocument();
      expect(within(row).getByText(item.issuer)).toHaveClass("text-muted-foreground");
      expect(within(row).getByText(`Expires ${formatTime(item.not_after)}`)).toBeInTheDocument();
      expect(within(row).getByText(expected[i][0])).toHaveClass(expected[i][1]);
    });
  });

  it("shows the tone of the nearest expiry in its header", () => {
    render(<CertificatesCard check={check([cert(995, 40), cert(993, 10)])} now={now} />);
    expect(screen.getAllByText("Expires in 10 days")).toHaveLength(2);
    for (const badge of screen.getAllByText("Expires in 10 days")) expect(badge).toHaveClass("text-amber-ink");
  });

  it("says when no certificate is served", () => {
    render(<CertificatesCard check={check([])} now={now} />);
    expect(screen.getByText("No certificate is served on the usual TLS ports.")).toBeInTheDocument();
    expect(screen.getByText("None", { selector: "[data-slot=badge]" })).toHaveClass("text-muted-foreground");
  });

  it("names the ports it checks in its footnote", () => {
    render(<CertificatesCard check={check([])} now={now} />);
    expect(
      screen.getByText(
        "Checks what the server serves on ports 443, 465, 636, 853, 993, 995, 5671, 6443, 8443, 8883 and 9443, for its own host name. Only the default site of each port is seen.",
      ),
    ).toHaveTextContent(/8443/);
  });
});
