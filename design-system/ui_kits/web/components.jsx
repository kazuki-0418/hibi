// Web kit components — small, factored, reusable.
// Loaded by index.html / edition.html via <script type="text/babel">.

const Topbar = ({ active, issue, date }) => (
  <header className="topbar">
    <div className="mark">日々</div>
    <nav>
      {['Archive','Today','Subscribe','About'].map(l => (
        <a key={l} href="#" className={active === l ? 'active' : ''}>{l}</a>
      ))}
    </nav>
    <div className="right">NO. {String(issue).padStart(4,'0')} · {date}</div>
  </header>
);

const MastheadWeb = ({ lede, stats }) => (
  <section className="masthead-web">
    <h1 className="big">日々</h1>
    <div className="side">
      <div className="eyebrow">Daily AI Newspaper · Tokyo</div>
      <p className="lede">{lede}</p>
      <div className="stats">
        {stats.map(s => (
          <div key={s.label}>
            <div className="n">{s.n}</div>
            <div className="l">{s.label}</div>
          </div>
        ))}
      </div>
    </div>
  </section>
);

const EditionRow = ({ no, date, title, cats }) => (
  <div className="edition-row">
    <div className="no">NO. {String(no).padStart(4,'0')}</div>
    <div className="date">{date}</div>
    <div className="title">{title}</div>
    <div className="cats">{cats.join(' · ')}</div>
    <div className="arr">→</div>
  </div>
);

const Feature = ({ no, day, title, storyCount, sourceCount, stories }) => (
  <div className="feature">
    <div className="left">
      <div className="eyebrow">No. {String(no).padStart(4,'0')} — {day}</div>
      <h3 dangerouslySetInnerHTML={{__html: title}}/>
      <div className="meta">{storyCount} STORIES · {sourceCount} SOURCES · 06:00 JST</div>
    </div>
    <div className="right">
      <ol>
        {stories.map((s,i) => (
          <li key={i}><span className="t">{s.title}</span><span className="c">{s.cat}</span></li>
        ))}
      </ol>
    </div>
  </div>
);

const SubscribeBand = () => (
  <section className="subscribe">
    <div className="eyebrow">Subscribe</div>
    <h2>毎朝六時、<br/>受信トレイへ。</h2>
    <p>無料。広告なし。配信解除はいつでも一クリック。</p>
    <form><input type="email" placeholder="you@example.com"/><button>Subscribe</button></form>
  </section>
);

const Foot = () => (
  <footer className="foot">
    <div className="left">
      <img src="seal.svg" width="56" height="56" alt="seal"/>
      <div className="jp">日々の小さな知らせ。<br/>Hibi · Daily · Tokyo</div>
    </div>
    <div className="right">
      Made by <a href="#">kazuki</a><br/>
      Powered by Claude Sonnet 4.6<br/>
      <a href="#">Source</a> · <a href="#">RSS</a>
    </div>
  </footer>
);

Object.assign(window, { Topbar, MastheadWeb, EditionRow, Feature, SubscribeBand, Foot });
