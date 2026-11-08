// Reusable customer details for this browser's phone demo. Never reuse incident facts or files.
(() => {
  const key='retakt.customer-profile.v1';
  const limits={name:160,email:254,phone:80,address:500,insurance_number:80};
  function clean(raw) {
    const out={};
    for(const [field,limit] of Object.entries(limits)) if(typeof raw?.[field]==='string') out[field]=raw[field].trim().slice(0,limit);
    if(raw?.demo===true) out.demo=true;
    return out;
  }
  function read() {try {return clean(JSON.parse(localStorage.getItem(key) || '{}'));}catch{return {};}}
  function save(raw) {
    const next={...read(),...clean(raw),updated_at:new Date().toISOString()};
    // Updating a real customer's data must never retain a demo-customer label.
    if(raw?.demo===false) delete next.demo;
    localStorage.setItem(key,JSON.stringify(next));return next;
  }
  function hasDetails(profile=read()) {return Object.keys(limits).some(field=>profile[field]);}
  window.RetaktProfile={read,save,clean,hasDetails};
})();
