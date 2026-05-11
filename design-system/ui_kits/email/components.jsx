// React JSX recreation of the Hibi daily email.
// Loaded by demo.html as <script type="text/babel" src="...">.

const Masthead = ({ issue, date, dayLabel }) => (
  <header className="masthead">
    <div className="lockup">
      <div className="mark">日々</div>
      <div className="meta"><strong>HIBI</strong><br/>DAILY · TOKYO</div>
    </div>
    <div className="date">
      {date}
      <div className="small">{dayLabel} · NO. {String(issue).padStart(4, '0')}</div>
    </div>
  </header>
);

const Standfirst = ({ children }) => (
  <section className="standfirst">{children}</section>
);

const Story = ({ index, category, source, minutes, title, lines, sourceUrl, sourceName }) => (
  <article className="story">
    <div className="num">{String(index).padStart(2, '0')}</div>
    <div>
      <div className="meta">
        <span className="cat">{category}</span>
        <span className="sep">·</span><span>{source}</span>
        <span className="sep">·</span><span>{minutes} min</span>
      </div>
      <h2>{title}</h2>
      {lines.map((l, i) => <p key={i}>{l}</p>)}
      <div className="src">Source <a href={sourceUrl}>{sourceName} ↗</a></div>
    </div>
  </article>
);

const Sources = ({ items }) => (
  <section className="sources">
    <div className="label">Sources scanned this morning</div>
    <ul>
      {items.map((s, i) => (
        <li key={i}><span>{s.name}</span><span className="kind">{s.kind}</span></li>
      ))}
    </ul>
  </section>
);

const Colophon = ({ generatedAt, model, sourceCount }) => (
  <footer className="colophon">
    <div className="seal"><img src="seal.svg" width="72" height="72" alt="日々 seal"/></div>
    <div className="meta">
      <div className="jp">日々の小さな知らせ。</div>
      Generated {generatedAt}<br/>
      {model} · {sourceCount} sources scanned<br/>
      <a href="#">Unsubscribe</a> &nbsp;·&nbsp; <a href="#">Archive</a>
    </div>
  </footer>
);

Object.assign(window, { Masthead, Standfirst, Story, Sources, Colophon });
