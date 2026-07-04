import type { Child } from "hono/jsx";

export function Layout(props: { title: string; pageClass?: string; children: Child }) {
  return (
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>{props.title}</title>
        <script src="https://unpkg.com/htmx.org@2.0.7"></script>
        <link rel="stylesheet" href="/static/app.css" />
      </head>
      <body>
        <a class="skip-link" href="#main-content">
          Skip to main content
        </a>
        <header class="masthead">
          <div class="width-container masthead-inner">
            <a href="/documents" class="brand">
              git<span class="brand-dash">&#8211;</span>legislation
            </a>
            <span class="masthead-note">United Kingdom legislation corpus</span>
          </div>
        </header>
        <div class="notice-strip">
          <div class="width-container">
            Experimental research corpus &middot; not an official source of law &middot; data Crown
            copyright, OGL v3.0
          </div>
        </div>
        <main id="main-content" class={`width-container page ${props.pageClass ?? ""}`}>
          {props.children}
        </main>
        <footer class="site-footer">
          <div class="width-container">
            <p>
              Contains public sector information licensed under the{" "}
              <a href="https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/">
                Open Government Licence v3.0
              </a>
              .
            </p>
            <p>
              Source data from <a href="https://www.legislation.gov.uk">legislation.gov.uk</a>, held
              as point-in-time snapshots.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
