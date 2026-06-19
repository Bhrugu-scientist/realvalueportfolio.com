/* Share buttons — WhatsApp, X, LinkedIn, Copy */
(function(){
  var url=encodeURIComponent(location.href), t=encodeURIComponent(document.title);
  function set(id,href){var e=document.getElementById(id);if(e)e.href=href;}
  set('sh-wa','https://wa.me/?text='+t+'%20'+url);
  set('sh-tw','https://twitter.com/intent/tweet?text='+t+'&url='+url);
  set('sh-li','https://www.linkedin.com/sharing/share-offsite/?url='+url);
  var cp=document.getElementById('sh-cp');
  if(cp)cp.onclick=function(){navigator.clipboard.writeText(location.href);this.textContent='Copied!';};
})();
