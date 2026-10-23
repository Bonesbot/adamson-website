// Served at https://siestareport.com/sitemap-index.xml by a host-scoped rewrite (public/_redirects).
import type { APIRoute } from 'astro';
import { srSitemapIndex } from '@/lib/crawlers';
export const GET: APIRoute = () =>
  new Response(srSitemapIndex(), { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
