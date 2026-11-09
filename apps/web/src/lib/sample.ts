// The log-parser task from bench/, bundled at build time so a visitor can post a real job and
// play a worker (honest or cheating) without writing anything.
import spec from "../../../../bench/tasks/log_parser/spec.md?raw";
import examples from "../../../../bench/tasks/log_parser/examples.json?raw";
import hidden from "../../../../bench/tasks/log_parser/hidden_tests.json?raw";
import reference from "../../../../bench/tasks/log_parser/reference.py?raw";
import generator from "../../../../bench/tasks/log_parser/gen_input.py?raw";
import honestFull from "../../../../bench/tasks/log_parser/submissions/honest_full/solution.py?raw";
import honestPartial from "../../../../bench/tasks/log_parser/submissions/honest_partial/solution.py?raw";
import memorizer from "../../../../bench/tasks/log_parser/submissions/cheat_memorizer/solution.py?raw";
import timebomb from "../../../../bench/tasks/log_parser/submissions/cheat_timebomb/solution.py?raw";
import injection from "../../../../bench/tasks/log_parser/submissions/cheat_injection/solution.py?raw";

export const SAMPLE_TITLE = "Parse application logs into JSON";
export const SAMPLE_SPEC = spec;

export function sampleSuite() {
  const h = JSON.parse(hidden);
  return {
    groups: h.groups,
    fresh: h.fresh,
    tests: h.tests,
    examples: JSON.parse(examples),
    reference,
    generator,
  };
}

export const SAMPLE_SUITE_SIZE = (() => {
  const h = JSON.parse(hidden);
  return { tests: h.tests.length as number, groups: Object.keys(h.groups).length };
})();

export interface SampleSubmission {
  key: string;
  label: string;
  hint: string;
  code: string;
}

export const SAMPLE_SUBMISSIONS: SampleSubmission[] = [
  { key: "honest_full", label: "Honest, complete", hint: "Should be paid in full.", code: honestFull },
  { key: "honest_partial", label: "Honest, skips a rule", hint: "Paid for the share that passes; the rest goes back to the buyer.", code: honestPartial },
  { key: "cheat_memorizer", label: "Cheat: memorized tests", hint: "Fails fresh inputs, so the hold is voided.", code: memorizer },
  { key: "cheat_injection", label: "Cheat: talks to the judge", hint: "Text aimed at the AI is a hard signal: voided.", code: injection },
  { key: "cheat_timebomb", label: "Cheat: hidden time bomb", hint: "Passes every test; only the AI review sees it, and sends it to a person.", code: timebomb },
];
