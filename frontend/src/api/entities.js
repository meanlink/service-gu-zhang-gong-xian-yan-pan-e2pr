import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const calibrations={
 list:()=>api('/calibrations'),
 get:id=>api('/calibrations/'+id),
 create:data=>api('/calibrations',{method:'POST',body:JSON.stringify(data)}),
 addCredential:(id,data)=>api('/calibrations/'+id+'/credentials',{method:'POST',body:JSON.stringify(data)}),
 publish:id=>api('/calibrations/'+id+'/publish',{method:'POST'}),
 revokeCredential:(id,credentialId,reason)=>api('/calibrations/'+id+'/credentials/'+credentialId+'/revoke',{method:'POST',body:JSON.stringify({reason})}),
 revoke:(id,reason)=>api('/calibrations/'+id+'/revoke',{method:'POST',body:JSON.stringify({reason})}),
 range:(id,source,target)=>api('/calibrations/'+id+'/range?source='+encodeURIComponent(source)+'&target='+encodeURIComponent(target)),
 conflicts:id=>api('/calibrations/'+id+'/conflicts'),
 affected:id=>api('/calibrations/'+id+'/affected'),
};
