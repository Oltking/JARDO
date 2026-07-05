import { useEffect, useState } from "react";

// Launch splash: the Jardo logo fades/scales in, holds briefly, then the whole
// overlay fades out to reveal the app. Pure CSS transitions; unmounts when done
// so it costs nothing after boot.
type Phase = "in" | "out" | "done";

export function Splash() {
  const [phase, setPhase] = useState<Phase>("in");

  useEffect(() => {
    const hold = window.setTimeout(() => setPhase("out"), 1500);
    const finish = window.setTimeout(() => setPhase("done"), 2100);
    return () => {
      window.clearTimeout(hold);
      window.clearTimeout(finish);
    };
  }, []);

  if (phase === "done") return null;

  return (
    <div className={`splash ${phase}`}>
      <div className="splash-inner">
        <img className="splash-logo" src="/jardo-logo.png" alt="Jardo" />
        <div className="splash-word">Jardo</div>
        <div className="splash-bar">
          <span />
        </div>
      </div>
    </div>
  );
}
