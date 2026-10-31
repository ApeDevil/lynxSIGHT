import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Candidate } from "../contracts/Candidate";
import { report } from "../fixtures";
import Review from "./Review.svelte";

const candidate = (acceptance: Candidate["acceptance"]): Candidate => ({
  workflow: "full",
  fit: null,
  validation: report,
  comparison: null,
  acceptance,
});

describe("Review", () => {
  afterEach(cleanup);

  it("installs a candidate the policy allows with one click", async () => {
    const onaccept = vi.fn();
    render(Review, { candidate: candidate({ decision: "install" }), onaccept, ondecline: vi.fn() });
    expect(screen.getByText("30.0 px")).toBeTruthy(); // median, without units the geometry lacks
    await fireEvent.click(screen.getByText("Accept"));
    expect(onaccept).toHaveBeenCalledWith(false);
  });

  it("asks for explicit confirmation before installing a doubtful candidate", async () => {
    const onaccept = vi.fn();
    render(Review, {
      candidate: candidate({ decision: "confirm_first", reason: "not better than the active calibration" }),
      onaccept,
      ondecline: vi.fn(),
    });
    const accept = screen.getByText("Accept") as HTMLButtonElement;
    expect(accept.disabled).toBe(true);
    await fireEvent.click(screen.getByLabelText("Install anyway"));
    expect(accept.disabled).toBe(false);
    await fireEvent.click(accept);
    expect(onaccept).toHaveBeenCalledWith(true);
  });
});
