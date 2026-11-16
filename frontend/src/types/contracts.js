/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean,calibration_scheme_id:number|null,calibration_revision:number|null,invalidated:boolean,invalidation_reason:string}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean,basis_revoked:boolean,revocation_note:string}} ReportSchedule */
/** @typedef {{id:number,name:string,reference_service:string,status:'draft'|'published'|'revoked',revision:number,consistent:boolean,conflict_count:number,service_count:number}} CalibrationScheme */
/** @typedef {{id:number,scheme_id:number,source_service:string,target_service:string,lower_min:number,upper_min:number,status:'active'|'revoked'}} CalibrationCredential */
/** @typedef {{reference:string,consistent:boolean,ranges:Object<string,{lower:number|null,upper:number|null,reachable:boolean}>,deltas:Object,conflicts:Object[],unreachable:string[]}} CalibrationSolution */
export {};
