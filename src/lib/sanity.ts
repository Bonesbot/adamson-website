import { createClient } from '@sanity/client';

export const sanityClient = createClient({
  projectId: 'l8q8hky0',
  dataset: 'production',
  apiVersion: '2026-04-22',
  useCdn: true, // Use CDN for faster reads at build time
});

// ---- GROQ Queries ----

/** Fetch all areas, ordered by sortOrder */
export async function getAreas() {
  return sanityClient.fetch(`
    *[_type == "area"] | order(sortOrder asc) {
      name,
      "slug": slug.current,
      tagline,
      description,
      highlights,
      zipCodes,
      marketStats,
      faqs,
      "heroImage": heroImage.asset->url,
      "cardImage": cardImage.asset->url
    }
  `);
}

/** Fetch a single area by slug */
export async function getAreaBySlug(slug: string) {
  return sanityClient.fetch(
    `
    *[_type == "area" && slug.current == $slug][0] {
      name,
      "slug": slug.current,
      tagline,
      description,
      highlights,
      zipCodes,
      marketStats,
      faqs,
      "heroImage": heroImage.asset->url,
      "cardImage": cardImage.asset->url
    }
  `,
    { slug }
  );
}

/** Fetch all area slugs (for static paths) */
export async function getAreaSlugs() {
  return sanityClient.fetch(`
    *[_type == "area"] { "slug": slug.current }
  `);
}

/** Fetch all market reports */
export async function getMarketReports() {
  return sanityClient.fetch(`
    *[_type == "marketReport"] | order(publishedAt desc) {
      title,
      "slug": slug.current,
      publishedAt,
      summary,
      "heroImage": heroImage.asset->url,
      body,
      faqs,
      "areas": areas[]->{ name, "slug": slug.current }
    }
  `);
}

/** Fetch a single market report by slug */
export async function getMarketReportBySlug(slug: string) {
  return sanityClient.fetch(
    `
    *[_type == "marketReport" && slug.current == $slug][0] {
      title,
      "slug": slug.current,
      publishedAt,
      summary,
      "heroImage": heroImage.asset->url,
      body,
      faqs,
      "areas": areas[]->{ name, "slug": slug.current }
    }
  `,
    { slug }
  );
}

/** Fetch site settings (singleton) */
export async function getSiteSettings() {
  return sanityClient.fetch(`
    *[_type == "siteSettings"][0] {
      agentName,
      tagline,
      heroHeading,
      heroSubheading,
      email,
      phone,
      address,
      bio,
      "headshot": headshot.asset->url,
      socialLinks
    }
  `);
}
