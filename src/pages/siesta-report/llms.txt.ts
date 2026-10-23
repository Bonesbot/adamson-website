// Served at https://siestareport.com/llms.txt by a host-scoped rewrite (public/_redirects).
import type { APIRoute } from 'astro';
import { srLlms } from '@/lib/crawlers';
export const GET: APIRoute = () =>
  new Response(srLlms(), { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
