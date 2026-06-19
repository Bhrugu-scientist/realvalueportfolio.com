/* Real Value blog — comments + likes, backed by your own Supabase.
   No third party. Setup (one time):
     1. In Supabase SQL editor, run the SQL in comments-setup.sql
     2. Fill CONFIG below with your project URL + anon (public) key
        (the anon key is safe to expose — Row Level Security protects the data)
*/
(function () {
  var CONFIG = {
    url:  "https://YOUR-PROJECT.supabase.co",   // <-- your Supabase project URL
    anon: "YOUR_SUPABASE_ANON_KEY"              // <-- your anon/public key
  };

  if (CONFIG.url.indexOf("YOUR-PROJECT") !== -1) {
    console.warn("[RV comments] Supabase not configured yet — fill CONFIG in comments.js");
  }

  var slug = document.body.getAttribute("data-slug") || location.pathname;
  var H = {
    "apikey": CONFIG.anon,
    "Authorization": "Bearer " + CONFIG.anon,
    "Content-Type": "application/json"
  };

  function api(path, opts) {
    return fetch(CONFIG.url + "/rest/v1/" + path, opts).then(function (r) {
      return r.ok ? (r.status === 201 ? r.json().catch(function(){return [];}) : r.json()) : Promise.reject(r);
    });
  }
  function esc(s){var d=document.createElement("div");d.textContent=s;return d.innerHTML;}
  function timeago(t){var s=(Date.now()-new Date(t))/1000;if(s<60)return"just now";if(s<3600)return Math.floor(s/60)+"m ago";if(s<86400)return Math.floor(s/3600)+"h ago";return Math.floor(s/86400)+"d ago";}

  // ── Likes ──────────────────────────────────────────────────────────────────
  function renderLike(el){
    var liked = localStorage.getItem("rvliked_"+slug);
    api("blog_likes?slug=eq."+encodeURIComponent(slug)+"&select=id", {headers:H})
      .then(function(rows){
        var n = rows.length;
        el.innerHTML = '<button id="rvlike" '+(liked?'disabled':'')+'>♥ '+(liked?'Liked':'Like')+' · '+n+'</button>';
        if(!liked) document.getElementById("rvlike").onclick = function(){
          api("blog_likes",{method:"POST",headers:H,body:JSON.stringify({slug:slug})})
            .then(function(){localStorage.setItem("rvliked_"+slug,"1");renderLike(el);});
        };
      }).catch(function(){el.innerHTML='';});
  }

  // ── Comments ────────────────────────────────────────────────────────────────
  function renderComments(listEl){
    api("blog_comments?slug=eq."+encodeURIComponent(slug)+"&order=created_at.desc",{headers:H})
      .then(function(rows){
        if(!rows.length){listEl.innerHTML='<p class="rvc-empty">Be the first to ask a question.</p>';return;}
        listEl.innerHTML = rows.map(function(c){
          return '<div class="rvc-item"><div class="rvc-head"><strong>'+esc(c.name||"Anonymous")+'</strong> <span>'+timeago(c.created_at)+'</span></div><div class="rvc-body">'+esc(c.body)+'</div></div>';
        }).join("");
      }).catch(function(){listEl.innerHTML='<p class="rvc-empty">Comments unavailable.</p>';});
  }

  function init(){
    var root = document.getElementById("rv-comments");
    if(!root) return;
    root.innerHTML =
      '<div id="rv-like"></div>'+
      '<h2>Questions & Comments</h2>'+
      '<p class="rvc-sub">Ask anything — Bhrugu replies personally.</p>'+
      '<form id="rvc-form"><input id="rvc-name" placeholder="Your name" maxlength="60"/>'+
      '<textarea id="rvc-body" placeholder="Your question or comment…" maxlength="1500" required></textarea>'+
      '<button type="submit">Post</button></form>'+
      '<div id="rvc-list"></div>';

    renderLike(document.getElementById("rv-like"));
    renderComments(document.getElementById("rvc-list"));

    document.getElementById("rvc-form").onsubmit = function(e){
      e.preventDefault();
      var name=document.getElementById("rvc-name").value.trim();
      var body=document.getElementById("rvc-body").value.trim();
      if(!body) return;
      api("blog_comments",{method:"POST",headers:H,body:JSON.stringify({slug:slug,name:name||"Anonymous",body:body})})
        .then(function(){document.getElementById("rvc-body").value="";renderComments(document.getElementById("rvc-list"));});
    };
  }
  if(document.readyState!=="loading") init(); else document.addEventListener("DOMContentLoaded", init);
})();
