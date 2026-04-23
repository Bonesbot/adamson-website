import {defineField, defineType} from 'sanity'

export default defineType({
  name: 'area',
  title: 'Area / Neighborhood',
  type: 'document',
  fields: [
    defineField({
      name: 'name',
      title: 'Area Name',
      type: 'string',
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'slug',
      title: 'URL Slug',
      type: 'slug',
      options: {source: 'name', maxLength: 96},
      validation: (Rule) => Rule.required(),
    }),
    defineField({
      name: 'tagline',
      title: 'Tagline',
      type: 'string',
      description: 'Short description shown on area cards (e.g. "Gulf-to-bay island living")',
    }),
    defineField({
      name: 'description',
      title: 'Full Description',
      type: 'text',
      rows: 4,
      description: 'Detailed area description for the area page',
    }),
    defineField({
      name: 'heroImage',
      title: 'Hero Image',
      type: 'image',
      options: {hotspot: true},
    }),
    defineField({
      name: 'cardImage',
      title: 'Card Image',
      type: 'image',
      options: {hotspot: true},
      description: 'Image shown on the area card on homepage',
    }),
    defineField({
      name: 'highlights',
      title: 'Highlights',
      type: 'array',
      of: [{type: 'string'}],
      description: 'Tags like "Gulf-front estates", "Private beach clubs"',
    }),
    defineField({
      name: 'zipCodes',
      title: 'ZIP Codes',
      type: 'array',
      of: [{type: 'string'}],
    }),
    defineField({
      name: 'marketStats',
      title: 'Market Statistics',
      type: 'object',
      fields: [
        defineField({name: 'medianPrice', title: 'Median Price', type: 'string'}),
        defineField({name: 'avgDom', title: 'Avg Days on Market', type: 'string'}),
        defineField({name: 'activeListings', title: 'Active Listings', type: 'string'}),
        defineField({name: 'soldLast90Days', title: 'Sold (Last 90 Days)', type: 'string'}),
        defineField({name: 'yoyPriceChange', title: 'YoY Price Change', type: 'string'}),
        defineField({name: 'pricePerSqFt', title: 'Price Per Sq Ft', type: 'string'}),
        defineField({name: 'lastUpdated', title: 'Last Updated', type: 'date'}),
      ],
    }),
    defineField({
      name: 'faqs',
      title: 'FAQs (AEO)',
      type: 'array',
      of: [
        {
          type: 'object',
          fields: [
            defineField({name: 'question', title: 'Question', type: 'string'}),
            defineField({name: 'answer', title: 'Answer', type: 'text', rows: 4}),
          ],
          preview: {
            select: {title: 'question'},
          },
        },
      ],
      description: 'FAQ pairs — these generate FAQPage schema markup for AI search engines',
    }),
    defineField({
      name: 'sortOrder',
      title: 'Sort Order',
      type: 'number',
      description: 'Lower numbers appear first',
    }),
  ],
  preview: {
    select: {
      title: 'name',
      subtitle: 'tagline',
      media: 'cardImage',
    },
  },
  orderings: [
    {
      title: 'Sort Order',
      name: 'sortOrder',
      by: [{field: 'sortOrder', direction: 'asc'}],
    },
  ],
})
