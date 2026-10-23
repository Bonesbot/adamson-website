// longboatlido.com/robots.txt (SITE=lll build; see src/lib/crawlers.ts)
import type { APIRoute } from 'astro';
import { robotsTxt, LLL } from '@/lib/crawlers';
export const GET: APIRoute = () =>
  new Response(robotsTxt(LLL, 'Longboat Lido: Longboat Key and Lido Key Real Estate'), { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
