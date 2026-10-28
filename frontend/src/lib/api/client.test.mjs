import test from 'node:test';
import assert from 'node:assert/strict';
import {createProject,uploadMedia,listMedia,ApiError} from './client.ts';
process.env.NEXT_PUBLIC_API_BASE_URL='http://127.0.0.1:8011';
const id='12345678-1234-1234-1234-123456789abc';
test('project JSON contract, credentials and signal', async()=>{ const c=new AbortController(); globalThis.fetch=async(url,o)=>{assert.equal(url,'http://127.0.0.1:8011/projects');assert.equal(o.credentials,'omit');assert.equal(o.signal,c.signal);assert.deepEqual(JSON.parse(o.body),{name:'Story'});return Response.json({id,name:'Story',created_at:'2026-01-01T00:00:00Z'})};assert.equal((await createProject(' Story ',c.signal)).id,id); });
test('multipart repeats files without manually setting content-type',async()=>{globalThis.fetch=async(url,o)=>{assert.equal(o.body.getAll('files').length,2);assert.equal(o.headers,undefined);return Response.json({items:[{id,project_id:id},{id,project_id:id}]})};await uploadMedia(id,[new File(['a'],'a.mp4'),new File(['b'],'b.mp4')]);});
test('normalized server errors preserve code and file index',async()=>{globalThis.fetch=async()=>Response.json({code:'invalid_upload',message:'Invalid video',file_index:1},{status:422});await assert.rejects(uploadMedia(id,[new File(['a'],'a.mp4')]),e=>e instanceof ApiError&&e.status===422&&e.fileIndex===1);});
test('network and cancellation are distinguished; never retried',async()=>{let count=0;globalThis.fetch=async()=>{count++;throw Error('offline')};await assert.rejects(listMedia(id),e=>e.code==='network_error');assert.equal(count,1);const c=new AbortController();c.abort();await assert.rejects(listMedia(id,c.signal),e=>e.code==='cancelled');});
test('validation prevents invalid identifiers and names before transport',async()=>{globalThis.fetch=async()=>{throw Error('must not fetch')};await assert.rejects(createProject('  '),e=>e.code==='invalid_name');assert.throws(()=>listMedia('../bad'),e=>e.code==='invalid_project');});

test("malformed successful response is ambiguous",async()=>{globalThis.fetch=async()=>new Response("broken",{status:201});await assert.rejects(createProject("Story"),e=>e.code==="invalid_response"&&e.status===0);});
