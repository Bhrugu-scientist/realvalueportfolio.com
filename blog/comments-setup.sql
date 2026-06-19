-- Real Value blog: comments + likes tables (run once in Supabase SQL editor)

-- Comments
create table if not exists blog_comments (
  id uuid primary key default gen_random_uuid(),
  slug text not null,
  name text default 'Anonymous',
  body text not null,
  created_at timestamptz default now()
);

-- Likes (one row per like)
create table if not exists blog_likes (
  id uuid primary key default gen_random_uuid(),
  slug text not null,
  created_at timestamptz default now()
);

-- Enable Row Level Security
alter table blog_comments enable row level security;
alter table blog_likes    enable row level security;

-- Anyone can read; anyone can insert; nobody can edit/delete via the public key
create policy "read comments"  on blog_comments for select using (true);
create policy "add comments"   on blog_comments for insert with check (char_length(body) between 1 and 1500);
create policy "read likes"     on blog_likes    for select using (true);
create policy "add likes"      on blog_likes    for insert with check (true);

-- Index for fast per-article lookups
create index if not exists idx_comments_slug on blog_comments(slug);
create index if not exists idx_likes_slug    on blog_likes(slug);
