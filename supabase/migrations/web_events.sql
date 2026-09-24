-- supabase/migrations/web_events.sql
--
-- First-party web analytics for adamsonfl.com, siestareport.com and longboatlido.com.
-- One row per event, written ONLY by the Netlify function `web-track` (service role).
-- RLS on with no policies: the anon key cannot read or write this table.
--
-- Events: pageview | engage (time on page + scroll, tied to its pageview by pid)
--         form_submit | contact_click (tel/sms/mailto) | outbound | form_spam (blocked bot)
--
-- Campaign attribution lives in the views, not the writer: vw_web_campaign maps
-- utm_campaign and the printed mailer paths (/GBC, ccshores) to a campaign key,
-- so a new mailer needs one CASE line, not a code deploy.

create table if not exists public.web_events (
  id            bigserial primary key,
  ts            timestamptz not null default now(),
  event         text not null default 'pageview',
  domain        text not null,
  path          text not null,
  query         text,
  title         text,
  referrer      text,
  referrer_host text,
  utm_source    text,
  utm_medium    text,
  utm_campaign  text,
  utm_content   text,
  utm_term      text,
  vid           text,          -- anonymous visitor id (first-party localStorage)
  sid           text,          -- session id (30 min inactivity)
  pid           text,          -- pageview id; engage rows share it
  new_visitor   boolean,
  new_session   boolean,
  device        text,          -- mobile | tablet | desktop
  screen_w      int,
  lang          text,
  ua            text,
  country       text,
  region        text,          -- state / subdivision code, e.g. FL
  city          text,
  postal        text,
  lat           numeric(6,3),  -- city-level only (3 dp)
  lon           numeric(7,3),
  tz            text,
  ip_hash       text,          -- salted sha256, never the raw IP
  engaged_sec   int,
  scroll_pct    int,
  label         text,          -- form name, link target, spam reasons
  is_bot        boolean not null default false,
  is_internal   boolean not null default false  -- Ryan/team devices (?internal=1)
);

create index if not exists web_events_ts_idx        on public.web_events (ts desc);
create index if not exists web_events_domain_ts_idx on public.web_events (domain, ts desc);
create index if not exists web_events_campaign_idx  on public.web_events (utm_campaign) where utm_campaign is not null;
create index if not exists web_events_pid_idx       on public.web_events (pid);
create index if not exists web_events_vid_idx       on public.web_events (vid);

alter table public.web_events enable row level security;
revoke all on public.web_events from anon, authenticated;

-- ── Clean pageviews: no bots, no team devices ──────────────────────────────────
create or replace view public.vw_web_pageviews as
select e.*,
       (e.ts at time zone 'America/New_York')::date as day_et,
       lower(regexp_replace(e.domain, '^www\.', '')) as site,
       coalesce(eng.engaged_sec, 0) as page_engaged_sec,
       coalesce(eng.scroll_pct, 0)  as page_scroll_pct
from public.web_events e
left join lateral (
  select max(x.engaged_sec) as engaged_sec, max(x.scroll_pct) as scroll_pct
  from public.web_events x
  where x.pid = e.pid and x.event = 'engage'
) eng on true
where e.event = 'pageview' and not e.is_bot and not e.is_internal;

-- ── Campaign key: UTM first, then the printed paths ─────────────────────────────
create or replace view public.vw_web_campaign as
select p.*,
  case
    when p.utm_campaign is not null and p.utm_campaign <> '' then p.utm_campaign
    when p.site = 'siestareport.com' and p.path ~* '^/gbc?(/|$)' then 'gb-owner-brief'
    when p.site = 'longboatlido.com' and p.path ~* '^/country-club-shores' and p.referrer_host ilike '%ccshores%' then 'ccshores'
    else null
  end as campaign,
  case
    when p.utm_medium = 'direct-mail' and p.utm_campaign is not null then 'qr-or-vanity'
    when p.site = 'siestareport.com' and p.path ~* '^/gbc?(/|$)' then 'typed'
    else null
  end as mail_entry,
  nullif(substring(p.path from '(?i)^/gbc/([a-z0-9-]+)'), '') as unit_code
from public.vw_web_pageviews p;

-- ── Daily rollup per site ───────────────────────────────────────────────────────
create or replace view public.vw_web_daily as
select day_et, site,
       count(*)                   as pageviews,
       count(distinct vid)        as visitors,
       count(distinct sid)        as sessions,
       count(distinct vid) filter (where new_visitor) as new_visitors,
       round(avg(nullif(page_engaged_sec, 0)))        as avg_engaged_sec
from public.vw_web_pageviews
group by 1, 2;

-- ── Report for the morning brief / Command Center ──────────────────────────────
-- web_report(p_day) -> jsonb for the ET day p_day (default: yesterday), with the
-- trailing 7 days for trend and all-time campaign totals. Read-only.
create or replace function public.web_report(p_day date default ((now() at time zone 'America/New_York')::date - 1))
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
with
yday  as (select * from vw_web_campaign where day_et = p_day),
last7 as (select * from vw_web_campaign where day_et >  p_day - 7 and day_et <= p_day),
prev7 as (select * from vw_web_campaign where day_et >  p_day - 14 and day_et <= p_day - 7),
sites as (
  select site,
         count(*) filter (where day_et = p_day)              as pv_yday,
         count(distinct vid) filter (where day_et = p_day)   as visitors_yday,
         count(distinct vid)                                  as visitors_7d
  from last7 group by site),
sites_prev as (select site, count(distinct vid) as visitors_prev7d from prev7 group by site),
camp as (
  select campaign,
         count(*) filter (where day_et = p_day)             as visits_yday,
         count(distinct vid) filter (where day_et = p_day)  as visitors_yday,
         count(*)                                           as visits_total,
         count(distinct vid)                                as visitors_total,
         min(day_et)                                        as first_seen,
         round(avg(nullif(page_engaged_sec, 0)))            as avg_engaged_sec
  from vw_web_campaign where campaign is not null group by campaign),
camp_entry as (
  select campaign, jsonb_object_agg(k, n) as by_entry from (
    select campaign, coalesce(mail_entry, 'other') k, count(distinct vid) n
    from vw_web_campaign where campaign is not null group by 1, 2) z group by campaign),
camp_place as (
  select campaign, jsonb_agg(jsonb_build_object('place', place, 'visitors', n) order by n desc) as places from (
    select campaign, concat_ws(', ', city, region, nullif(country, 'US')) place, count(distinct vid) n,
           row_number() over (partition by campaign order by count(distinct vid) desc) rn
    from vw_web_campaign where campaign is not null and city is not null group by 1, 2) z
  where rn <= 5 group by campaign),
camp_units as (
  select campaign, jsonb_agg(distinct unit_code) as unit_codes
  from vw_web_campaign where unit_code is not null group by campaign)
select jsonb_build_object(
  'day', p_day,
  'sites', coalesce((select jsonb_agg(jsonb_build_object(
        'site', s.site, 'pageviews', s.pv_yday, 'visitors', s.visitors_yday,
        'visitors_7d', s.visitors_7d, 'visitors_prev_7d', coalesce(sp.visitors_prev7d, 0))
        order by s.visitors_7d desc)
     from sites s left join sites_prev sp using (site)), '[]'::jsonb),
  'campaigns', coalesce((select jsonb_agg(jsonb_build_object(
        'campaign', c.campaign, 'visits_yday', c.visits_yday, 'visitors_yday', c.visitors_yday,
        'visits_total', c.visits_total, 'visitors_total', c.visitors_total, 'first_seen', c.first_seen,
        'avg_engaged_sec', c.avg_engaged_sec, 'by_entry', ce.by_entry,
        'top_places', coalesce(cp.places, '[]'::jsonb), 'unit_codes', coalesce(cu.unit_codes, '[]'::jsonb))
        order by c.visits_total desc)
     from camp c left join camp_entry ce using (campaign) left join camp_place cp using (campaign)
     left join camp_units cu using (campaign)), '[]'::jsonb),
  'top_pages', coalesce((select jsonb_agg(jsonb_build_object('site', site, 'path', path, 'views', n) order by n desc)
     from (select site, path, count(*) n from yday group by 1, 2 order by 3 desc limit 8) t), '[]'::jsonb),
  'top_places_7d', coalesce((select jsonb_agg(jsonb_build_object('place', place, 'visitors', n) order by n desc)
     from (select concat_ws(', ', city, region, nullif(country, 'US')) place, count(distinct vid) n
           from last7 where city is not null group by 1 order by 2 desc limit 8) t), '[]'::jsonb),
  'top_sources_7d', coalesce((select jsonb_agg(jsonb_build_object('source', src, 'sessions', n) order by n desc)
     from (select coalesce(nullif(utm_source, ''), referrer_host, '(direct)') src, count(distinct sid) n
           from last7 group by 1 order by 2 desc limit 8) t), '[]'::jsonb),
  'actions_yday', jsonb_build_object(
     'contact_clicks', (select count(*) from web_events where event = 'contact_click' and not is_internal and not is_bot
                          and (ts at time zone 'America/New_York')::date = p_day),
     'form_submits',   (select count(*) from web_events where event = 'form_submit' and not is_internal and not is_bot
                          and (ts at time zone 'America/New_York')::date = p_day)),
  'leads_yday', jsonb_build_object(
     'real',         (select count(*) from leads where coalesce(status, '') <> 'spam'
                        and (created_at at time zone 'America/New_York')::date = p_day),
     'flagged_spam', (select count(*) from leads where status = 'spam'
                        and (created_at at time zone 'America/New_York')::date = p_day),
     'bots_blocked', (select count(*) from web_events where event = 'form_spam'
                        and (ts at time zone 'America/New_York')::date = p_day))
);
$$;

revoke all on function public.web_report(date) from public, anon, authenticated;
