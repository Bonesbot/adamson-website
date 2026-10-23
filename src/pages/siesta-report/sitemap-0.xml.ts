// Served at https://siestareport.com/sitemap-0.xml by a host-scoped rewrite (public/_redirects).
import type { APIRoute } from 'astro';
import { srSitemap } from '@/lib/crawlers';
export const GET: APIRoute = () =>
  new Response(srSitemap(), { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
