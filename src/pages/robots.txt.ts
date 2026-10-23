// adamsonfl.com/robots.txt (generated per host; see src/lib/crawlers.ts)
import type { APIRoute } from 'astro';
import { robotsTxt, HUB } from '@/lib/crawlers';
export const GET: APIRoute = () =>
  new Response(robotsTxt(HUB, 'Ryan Adamson Luxury Real Estate, Sarasota FL'), { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
