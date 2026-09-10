/**
 * Shared helpers for the co-branded partner-site area pages
 * (longboatlido.com and siestareport.com home pages).
 *
 * The daily pipeline writes its living market answers for the hub site, in Ryan's
 * voice and with em dashes; partner pages re-voice them to the partnership at build
 * time. Kept here so the page frontmatter (JSON-LD) and the page body component
 * compute the exact same FAQ list and as-of label.
 */

export interface CobrandNames {
  /** "Anne and Ryan" */
  agentsShort: string;
  /** "Anne Schneider and Ryan Adamson" */
  agentsFull: string;
}

export interface Faq { question: string; answer: string }

export function makeCobrand(names: CobrandNames) {
  return (s: string): string => String(s ?? '')
    .replace(/Ryan Adamson's local market guidance/g, `${names.agentsShort}'s local market guidance`)
    .replace(/Ryan Adamson/g, names.agentsFull)
    .replace(/\s*—\s*/g, ', ');
}

function lookupPath(obj: any, path: string): any {
  return path.split('.').reduce((o: any, k: string) => (o == null ? undefined : o[k]), obj);
}

export function buildAreaModel(stats: any, area: any, media: any, names: CobrandNames) {
  const cobrand = makeCobrand(names);

  const asOf = stats?.lastUpdated
    ? new Date(stats.lastUpdated).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' })
    : '';
  const asOfIso = String(stats?.lastUpdated || '').slice(0, 10);

  // Editorial FAQ answers in areas.json may carry {{tokens}} resolved against the stats
  // file; any FAQ whose tokens cannot all be resolved is dropped rather than shown with gaps.
  const interpCtx = { ...(stats || {}), asOf };
  const interpolate = (text: string): string | null => {
    let ok = true;
    const out = String(text).replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_m: string, p: string) => {
      const v = lookupPath(interpCtx, p);
      if (v === undefined || v === null || v === '') { ok = false; return ''; }
      return String(v);
    });
    return ok ? out : null;
  };

  const livingFaqs: Faq[] = ((stats?.marketQuestions) || [])
    .map((q: any) => ({ question: cobrand(q.q), answer: cobrand(q.a) }));
  const editorialFaqs: Faq[] = ((area?.faqs) || [])
    .map((f: any) => ({ question: f.question, answer: interpolate(f.answer) }))
    .filter((f: any) => f.answer !== null)
    .map((f: any) => ({
      question: cobrand(String(f.question).replace('average home price', 'median home price')),
      answer: cobrand(f.answer),
    }));
  const faqs: Faq[] = [...livingFaqs, ...editorialFaqs];

  const summary: string = media?.summary || cobrand(area?.description || '');

  return { asOf, asOfIso, faqs, cobrand, summary };
}
