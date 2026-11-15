/* Karyaniti — tweak controls.
   Wires a small set of CSS variables / data attributes to the tweaks panel
   so the user can shape the design in-page. */

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#b8893a",
  "queryStyle": "raised",
  "motion": "lively",
  "grain": 55,
  "headlineItalic": true,
  "showTicker": true,
  "density": "comfortable"
}/*EDITMODE-END*/;

function applyTweaks(t){
  const r = document.documentElement;
  r.style.setProperty('--gold', t.accent);
  r.style.setProperty('--gold-2', shade(t.accent, +14));
  r.style.setProperty('--gold-3', shade(t.accent, -22));
  r.style.setProperty('--grain-opacity', (t.grain/100).toFixed(2));
  r.dataset.queryStyle = t.queryStyle;
  r.dataset.motion = t.motion;
  r.dataset.density = t.density;
  r.dataset.italic = t.headlineItalic ? '1' : '0';
  r.dataset.ticker = t.showTicker ? '1' : '0';
}

function shade(hex, pct){
  const c = hex.replace('#','');
  const n = parseInt(c.length===3 ? c.split('').map(x=>x+x).join('') : c, 16);
  let r = (n>>16)&255, g = (n>>8)&255, b = n&255;
  const f = pct < 0 ? (1+pct/100) : 1;
  const a = pct < 0 ? 0 : (pct/100);
  r = Math.round(r*f + (255-r)*a*(pct>0?1:0));
  g = Math.round(g*f + (255-g)*a*(pct>0?1:0));
  b = Math.round(b*f + (255-b)*a*(pct>0?1:0));
  return '#' + [r,g,b].map(v => Math.max(0,Math.min(255,v)).toString(16).padStart(2,'0')).join('');
}

function App(){
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  React.useEffect(() => { applyTweaks(t); }, [t]);

  return (
    <TweaksPanel>
      <TweakSection label="Query card" />
      <TweakRadio label="Style" value={t.queryStyle}
                  options={['raised','glass','inset']}
                  onChange={v => setTweak('queryStyle', v)} />
      <TweakSection label="Motion" />
      <TweakRadio label="Pulse" value={t.motion}
                  options={['still','subtle','lively']}
                  onChange={v => setTweak('motion', v)} />
      <TweakSection label="Texture" />
      <TweakSlider label="Paper grain" value={t.grain} min={0} max={100} unit="%"
                   onChange={v => setTweak('grain', v)} />
      <TweakColor  label="Accent" value={t.accent}
                   options={['#b8893a','#923224','#3d6b3a','#3d2e1f','#56504a']}
                   onChange={v => setTweak('accent', v)} />
      <TweakSection label="Layout" />
      <TweakRadio  label="Density" value={t.density}
                   options={['compact','comfortable','airy']}
                   onChange={v => setTweak('density', v)} />
      <TweakToggle label="Italic display" value={t.headlineItalic}
                   onChange={v => setTweak('headlineItalic', v)} />
      <TweakToggle label="Live ticker" value={t.showTicker}
                   onChange={v => setTweak('showTicker', v)} />
    </TweaksPanel>
  );
}

// Apply once on initial load too, before tweaks panel even mounts,
// so SSR-equivalent first paint matches.
applyTweaks(TWEAK_DEFAULTS);

const root = document.createElement('div');
document.body.appendChild(root);
ReactDOM.createRoot(root).render(<App />);
