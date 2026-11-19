import {beforeEach, expect, it, vi} from "vitest";
import {isValidElement, type ReactElement} from "react";
const h=vi.hoisted(()=>({slots:[] as any[],cursor:0,busy:null as string|null,preview:vi.fn(),commit:vi.fn(),project:vi.fn(),run:vi.fn(),dispatch:vi.fn(),toast:vi.fn()}));
vi.mock("react",async load=>({...await load<typeof import("react")>(),useState:(value:unknown)=>{const i=h.cursor++;if(!(i in h.slots))h.slots[i]=value;return[h.slots[i],(next:unknown)=>{h.slots[i]=next;}];},useEffect:()=>{}}));
vi.mock("react-i18next",async load=>({...await load<typeof import("react-i18next")>(),useTranslation:()=>({t:i18n.t.bind(i18n),i18n})}));
vi.mock("../../src/state/store",()=>({useStore:()=>({state:{view:{bundle:{project:{project_id:'p'}}},busy:h.busy},run:h.run,dispatch:h.dispatch,toast:h.toast}),uiStore:{getState:()=>({state:{view:{bundle:{project:{project_id:'p'}}}}})}}));
vi.mock("../../src/client",()=>({engine:{previewWeatherFile:h.preview,importWeatherFile:h.commit,project:h.project}}));
import i18n from "../../src/i18n";
import {ImportHub,WeatherFilePreview,canUseWeather} from "../../src/Modals";
import {Button} from "../../src/ui/kit";
import {api} from "../../src/api";
import {mockApi} from "../../src/demo/mockApi";
import {DemoUnavailableError} from "../../src/engine/adapter";
import type {WeatherImportPreview} from "../../src/types";
const preview:WeatherImportPreview={format:'epw',filename:'synthetic.epw',sha256:'a'.repeat(64),location:{latitude_deg:-6.2,longitude_deg:106.8,elevation_m:20},site:{latitude_deg:-6.2,longitude_deg:107.9,elevation_m:20,timezone:'Asia/Jakarta'},distance_km:120,
 time_zone:{source_timezone:'UTC+07:00',source_utc_offset_hours:7,canonical_timezone:'UTC+07:00',site_timezone:'Asia/Jakarta',site_standard_utc_offset_hours:7},period:{start:'2026-01-01T00:00:00+07:00',end:'2026-01-01T04:00:00+07:00'},step_minutes:60,row_count:4,variables:['ghi_w_m2'],typical_year:true,
 monthly_ghi_kwh_m2:[.7,...Array(11).fill(0)],annual_ghi_kwh_m2:.7,qc:{status:'passed',findings:[]},warnings:[{code:'weather_location_distant',message:'The weather file location is 120 km from the site.',distance_km:120}],requires_accept_distant_location:true};
function tree(v:unknown):ReactElement<any>[]{if(Array.isArray(v))return v.flatMap(tree);if(!isValidElement(v))return[];const n=v as ReactElement<any>;return[n,...tree(n.props.children)];}
function text(v:unknown):string{if(Array.isArray(v))return v.map(text).join(' ');if(isValidElement(v))return text((v as ReactElement<any>).props.children);return v==null||typeof v==='boolean'?'':String(v);}
function render(){h.cursor=0;return tree(ImportHub({initial:'meteo',onClose:()=>{}}));}
function button(label:string){return render().find(n=>n.type===Button&&text(n.props.children)===label)!;}
async function settle(){for(let i=0;i<30;i++)await Promise.resolve();}
beforeEach(()=>{vi.clearAllMocks();vi.unstubAllGlobals();h.slots=[];h.busy=null;void i18n.changeLanguage('en');h.run.mockImplementation(async(_label,op)=>op());h.project.mockResolvedValue({bundle:{project:{project_id:'p'}}});});
it('renders all twelve months, period, site checks, timezone and QC; gates distance consent',()=>{
 const commit=vi.fn(),accept=vi.fn();
 const props={preview,busy:false,accepted:false,committed:false,onCommit:commit,onAccept:accept};
 const nodes=tree(WeatherFilePreview(props)),all=text(nodes);
 expect(all).toContain('120');expect(all).toContain('106.8');expect(all).toContain('107.9');expect(all).toContain('UTC+07:00');expect(all).toContain('2026-01-01T00:00:00+07:00');expect(all).toContain('passed');
 expect(nodes.filter(n=>n.type==='tbody')[0].props.children).toHaveLength(12);
 const use=nodes.find(n=>n.type===Button)!;expect(use.props.disabled).toBe(true);use.props.onClick();expect(commit).not.toHaveBeenCalled();
 tree(WeatherFilePreview({...props,accepted:true})).find(n=>n.type===Button)!.props.onClick();expect(commit).toHaveBeenCalledOnce();
 expect(canUseWeather({...preview,qc:{status:'failed',findings:[]}},true)).toBe(false);
 expect(canUseWeather({...preview,qc:{status:'warning',findings:[{rule_id:'bad',message:'bad',severity:'blocking_error'}]}},true)).toBe(false);
 expect(canUseWeather({...preview,requires_accept_distant_location:false},false)).toBe(true);
});
it('previews without committing; explicit use sends consent and reloads the project',async()=>{
 const file=new File(['synthetic'],'synthetic.epw');h.slots=['meteo',file];h.preview.mockResolvedValue(preview);
 button('Detect and preview').props.onClick();await settle();expect(h.preview).toHaveBeenCalledWith('p',file);expect(h.commit).not.toHaveBeenCalled();
 let child=render().find(n=>n.type===WeatherFilePreview)!;expect(child.props.accepted).toBe(false);
 child.props.onAccept(true);h.commit.mockResolvedValue({selection:{name:'epw file synthetic.epw'},duplicate:false});
 child=render().find(n=>n.type===WeatherFilePreview)!;child.props.onCommit();await settle();
 expect(h.commit).toHaveBeenCalledWith('p',file,true);expect(h.project).toHaveBeenCalledWith('p');expect(h.dispatch).toHaveBeenCalledWith({type:'setView',view:expect.any(Object)});expect(h.toast).toHaveBeenCalledWith('ok','Weather selected: epw file synthetic.epw.');
});
it('busy state refuses preview; file replacement clears the preview and consent',()=>{
 const file=new File(['synthetic'],'synthetic.epw');h.slots=['meteo',file,null,[],false,null,null,false,null,preview,true];h.busy='Other edit';
 expect(button('Detect and preview').props.disabled).toBe(true);button('Detect and preview').props.onClick();expect(h.preview).not.toHaveBeenCalled();
 h.busy=null;render().find(n=>n.type==='input'&&n.props.type==='file')!.props.onChange({target:{files:[new File(['other'],'other.epw')]}});
 expect(render().find(n=>n.type===WeatherFilePreview)).toBeUndefined();expect(h.slots[10]).toBe(false);
});
it('renders Indonesian warning text and preserves unknown service messages',()=>{
 void i18n.changeLanguage('id');const nodes=WeatherFilePreview({preview:{...preview,warnings:[...preview.warnings,{code:'future_warning',message:'Service fallback'}]},busy:false,accepted:false,committed:false,onAccept:()=>{},onCommit:()=>{}});
 expect(text(nodes)).toContain('berjarak 120 km');expect(text(nodes)).toContain('Service fallback');
});
it('uses raw-body preview and commit flags; demo refuses both methods',async()=>{
 const fetch=vi.fn().mockImplementation(async()=>new Response(JSON.stringify(preview),{status:200}));vi.stubGlobal('fetch',fetch);
 const file=new File(['synthetic'],'weather file.epw');await api.previewWeatherFile('p',file);await api.importWeatherFile('p',file,true);
 expect(fetch.mock.calls[0][0]).toBe('/api/projects/p/weather/import?filename=weather%20file.epw&dry_run=true');
 expect(fetch.mock.calls[1][0]).toContain('dry_run=false&accept_distant_location=true');
 expect(fetch.mock.calls[0][1].body).toBe(file);expect(fetch.mock.calls[0][1].headers['Content-Type']).toBe('application/octet-stream');
 await expect(mockApi.previewWeatherFile('p',file)).rejects.toBeInstanceOf(DemoUnavailableError);
 await expect(mockApi.importWeatherFile('p',file,true)).rejects.toThrow('Importing weather files needs the engine');
});
