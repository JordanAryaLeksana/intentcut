const swatches = [
  { name: "Canvas", token: "background", color: "bg-background" },
  { name: "Surface", token: "surface", color: "bg-surface" },
  { name: "Elevated", token: "surface-elevated", color: "bg-surface-elevated" },
  { name: "Foreground", token: "foreground", color: "bg-foreground" },
  { name: "Muted text", token: "muted-foreground", color: "bg-muted-foreground" },
  { name: "Mint", token: "primary", color: "bg-primary" },
];

export default function Home() {
  return (
    <>
      <a href="#main" className="button button-primary sr-only focus:not-sr-only focus:absolute focus:left-6 focus:top-4 focus:z-10">Skip to content</a>
      <div className="mx-auto max-w-7xl px-6 sm:px-10 lg:px-16">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b py-7">
          <span className="text-xl font-semibold tracking-tight" translate="no"><span className="mr-2 text-primary" aria-hidden="true">/</span>IntentCut</span>
          <span className="eyebrow">Design foundation <span className="technical ml-3 text-primary">01</span></span>
        </header>
        <main id="main" tabIndex={-1} className="py-14 sm:py-20">
          <section aria-labelledby="identity" className="grid gap-10 lg:grid-cols-[1.4fr_1fr] lg:items-end">
            <div>
              <p className="eyebrow mb-6">A considered space for creative work</p>
              <h1 id="identity" className="max-w-3xl text-5xl font-medium sm:text-6xl lg:text-7xl">Your AI<br />Storytelling <span className="text-primary">Director.</span></h1>
            </div>
            <div className="max-w-md lg:pb-2">
              <p className="text-lg text-muted-foreground">Quiet surfaces. Clear intention. Room for the story.</p>
              <p className="mt-4 text-sm text-muted-foreground">A visual study of the IntentCut design language. Typography, surfaces, and controls for a focused editing environment.</p>
              <div className="mt-7 flex flex-wrap gap-3">
                <a className="button button-primary" href="#material">Explore the palette <span aria-hidden="true" className="ml-3">↗</span></a>
                <a className="button button-secondary" href="#type">View typography</a>
              </div>
            </div>
          </section>

          <section id="material" aria-labelledby="material-heading" className="mt-16 sm:mt-24">
            <div className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
              <h2 id="material-heading" className="text-2xl font-medium">Material & light</h2>
              <p className="eyebrow">01 / Semantic palette</p>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              {swatches.map(({ name, token, color }) => (
                <div key={token} className="min-w-0 rounded-lg border bg-card p-2">
                  <div className={`${color} h-20 rounded-sm border`} aria-hidden="true" />
                  <div className="px-1 pb-2 pt-4">
                    <h3 className="text-sm font-medium">{name}</h3>
                    <p className="technical mt-2 break-words text-xs text-muted-foreground">{token}</p>
                  </div>
                </div>
              ))}
            </div>
          </section>

          <div className="mt-10 grid gap-6 lg:grid-cols-2">
            <section id="type" aria-labelledby="type-heading" className="rounded-xl border bg-card p-6 sm:p-8">
              <p className="eyebrow mb-8">02 / Type & rhythm</p>
              <h2 id="type-heading" className="text-3xl font-medium sm:text-4xl">Every detail<br />serves the story.</h2>
              <p className="mt-5 max-w-sm text-muted-foreground">Geist Sans keeps the interface clear and composed. Geist Mono gives technical values a steady rhythm.</p>
              <div className="mt-8 border-t pt-6">
                <p className="eyebrow mb-3">Timecode specimen · Geist Mono</p>
                <p className="technical text-3xl tracking-tight sm:text-4xl">00:00:00:00</p>
              </div>
            </section>
            <section aria-labelledby="panel-heading" className="overflow-hidden rounded-xl border bg-card shadow-panel">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-5 sm:px-8">
                <h2 id="panel-heading" className="text-base font-medium tracking-normal">Surface study</h2>
                <span className="eyebrow">03 / Panel specimen</span>
              </div>
              <div className="p-6 sm:p-8">
                <div className="rounded-lg border bg-surface-elevated p-6">
                  <span className="mb-5 block h-1 w-8 rounded-full bg-primary" aria-hidden="true" />
                  <h3 className="text-xl font-medium">Space to focus</h3>
                  <p className="mt-3 text-sm text-muted-foreground">An elevated surface brings context forward without competing with the work.</p>
                </div>
                <dl className="mt-6 space-y-4 text-sm">
                  <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Treatment</dt><dd>Solid, restrained</dd></div>
                  <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Accent</dt><dd className="text-primary">Intentional mint</dd></div>
                  <div className="flex justify-between gap-4 border-t pt-4"><dt className="text-muted-foreground">Purpose</dt><dd>Visual reference only</dd></div>
                </dl>
              </div>
            </section>
          </div>
        </main>
        <footer className="flex flex-wrap justify-between gap-3 border-t py-6 text-xs text-muted-foreground"><p>IntentCut · Your AI Storytelling Director</p><p>Design study / M3.1.2</p></footer>
      </div>
    </>
  );
}
