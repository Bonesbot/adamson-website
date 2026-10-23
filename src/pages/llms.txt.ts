// adamsonfl.com/llms.txt: the hub answer sheet for AI crawlers (see src/lib/crawlers.ts)
import type { APIRoute } from 'astro';
import { hubLlms } from '@/lib/crawlers';
export const GET: APIRoute = () =>
  new Response(hubLlms(), { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
