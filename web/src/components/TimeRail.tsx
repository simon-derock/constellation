import { useAsOf } from "../asof";
import { FIRST_DAY, LAST_DAY, RAIL_DAYS, railIndex } from "../lib/scale";

// the one control that sets "as of": it moves the ownership view and frames every perspective question
export function TimeRail() {
  const { day, setDay } = useAsOf();
  return (
    <div className="rail">
      <label htmlFor="as-of" className="rail-label">
        As of day <output htmlFor="as-of">{day}</output>
      </label>
      <input
        id="as-of"
        type="range"
        min={0}
        max={RAIL_DAYS.length - 1}
        step={1}
        value={railIndex(day)}
        onChange={(event) => setDay(RAIL_DAYS[Number(event.target.value)] ?? LAST_DAY)}
        aria-valuetext={`day ${day}`}
      />
      <div className="rail-ends" aria-hidden="true">
        <span>{FIRST_DAY}</span>
        <span>0: records begin</span>
        <span>{LAST_DAY}</span>
      </div>
    </div>
  );
}
