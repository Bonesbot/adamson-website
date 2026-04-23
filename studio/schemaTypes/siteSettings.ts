import {defineField, defineType} from 'sanity'

export default defineType({
  name: 'siteSettings',
  title: 'Site Settings',
  type: 'document',
  fields: [
    defineField({
      name: 'agentName',
      title: 'Agent Name',
      type: 'string',
      initialValue: 'Ryan Adamson',
    }),
    defineField({
      name: 'tagline',
      title: 'Hero Tagline',
      type: 'string',
      description: 'The tagline shown in the hero section',
      initialValue: 'Integrity | Passion | Professionalism',
    }),
    defineField({
      name: 'heroHeading',
      title: 'Hero Heading',
      type: 'string',
      initialValue: "Luxury Real Estate on Sarasota's Barrier Islands",
    }),
    defineField({
      name: 'heroSubheading',
      title: 'Hero Subheading',
      type: 'text',
      rows: 2,
    }),
    defineField({
      name: 'email',
      title: 'Email',
      type: 'string',
      initialValue: 'Ryan@Adamson-Group.com',
    }),
    defineField({
      name: 'phone',
      title: 'Phone',
      type: 'string',
    }),
    defineField({
      name: 'address',
      title: 'Office Address',
      type: 'string',
      initialValue: '423 St Armands Cir, Sarasota, FL 34236',
    }),
    defineField({
      name: 'bio',
      title: 'About / Bio',
      type: 'array',
      of: [{type: 'block'}],
      description: 'Rich text bio for the About page',
    }),
    defineField({
      name: 'headshot',
      title: 'Headshot Photo',
      type: 'image',
      options: {hotspot: true},
    }),
    defineField({
      name: 'socialLinks',
      title: 'Social Media Links',
      type: 'object',
      fields: [
        defineField({name: 'facebook', title: 'Facebook URL', type: 'url'}),
        defineField({name: 'instagram', title: 'Instagram URL', type: 'url'}),
        defineField({name: 'linkedin', title: 'LinkedIn URL', type: 'url'}),
        defineField({name: 'youtube', title: 'YouTube URL', type: 'url'}),
      ],
    }),
  ],
  preview: {
    prepare() {
      return {title: 'Site Settings'}
    },
  },
})
