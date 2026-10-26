// Served at https://siestareport.com/robots.txt by a host-scoped rewrite (public/_redirects).
import type { APIRoute } from 'astro';
import { robotsTxt, SR, IDX_DENY } from '@/lib/crawlers';
export const GET: APIRoute = () =>
  new Response(robotsTxt(SR, 'Siesta Report: Siesta Key Real Estate, by the Numbers', IDX_DENY), { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
