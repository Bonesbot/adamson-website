// longboatlido.com/llms.txt (SITE=lll build; see src/lib/crawlers.ts)
import type { APIRoute } from 'astro';
import { lllLlms } from '@/lib/crawlers';
export const GET: APIRoute = () =>
  new Response(lllLlms(), { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
