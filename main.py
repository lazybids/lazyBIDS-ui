import html 
import shutil
import tempfile
import os
from PIL import Image
from py7zr import unpack_7zarchive
shutil.register_unpack_format('7zip', ['.7z'], unpack_7zarchive)
from typing import Optional, Union
from fastapi import FastAPI, Request, Header, Form, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import lazybids
from dotenv import load_dotenv, dotenv_values 
# loading variables from .env file
load_dotenv()

import pandas as pd
from typing import List
import functools

import asyncio

from src import models, worker

import datetime
from sqlmodel import Field, Session, SQLModel, create_engine, select

import hashlib

from pretty_html_table import build_table

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
engine = create_engine("sqlite:///database.db")
templates = Jinja2Templates(directory="templates")


async def error(request, e):
    return templates.TemplateResponse("components/error.html", context = {"request": request,'error':e} )

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):

    context = {"request": request,'mainViewURL':'/datasets'}
    return templates.TemplateResponse("root.html", context )


@app.get("/datasets", response_class=HTMLResponse)
async def datasets(request: Request):
    print(request.headers.keys())
    if not('hx-request' in request.headers.keys()):
        return await root(request)
    else:
        with Session(engine) as session:
            statement = select(models.Dataset)
            datasets = session.exec(statement).all()
            for dataset in datasets:
                if dataset.taskID:
                    if dataset.state in ['SUCCESS','FAILURE']:
                        continue
                    else:
                        task = worker.openneuro_download.AsyncResult(dataset.taskID)
                        dataset.state = task.state
                        session.add(dataset)
                        session.commit()
                if not(dataset.taskID) and dataset.state != 'SUCCESS':
                        dataset.state = 'SUCCESS'
                        session.add(dataset)
                        session.commit()

            context = {"request": request,'datasets':datasets}
            output = templates.TemplateResponse("components/datasets.html", context )
        return output
    
@app.get("/dataset_card/{ds_id}", response_class=HTMLResponse)
async def datasets(request: Request, ds_id:int):
    if not('hx-request' in request.headers.keys()):
        return await root(request)
    else:
        with Session(engine) as session:
            statement = select(models.Dataset).where(models.Dataset.id==ds_id)
            dataset = session.exec(statement).first()
            if dataset.taskID:
                if dataset.state in ['SUCCESS','FAILURE']:
                    print('ready')
                else:
                    task = worker.openneuro_download.AsyncResult(dataset.taskID)
                    dataset.state = task.state
                    session.add(dataset)
                    session.commit()
            if not(dataset.taskID) and dataset.state != 'SUCCESS':
                    dataset.state = 'SUCCESS'
                    session.add(dataset)
                    session.commit()

            context = {"request": request,'dataset':dataset}
            output = templates.TemplateResponse("components/dataset_card.html", context )
        return output


@app.post("/datasets/create", response_class=HTMLResponse)
async def create_dataset(request: Request, 
                         name: str = Form(...), 
                         folder: Optional[str] = Form(None), 
                         DatabaseID: Optional[str] = Form(None),
                         Version: Optional[str] = Form(None), 
                         CopyFolder: Optional[str] = Form(None),
                         icon: Union[UploadFile, None] = None, 
                         zipfile:Union[UploadFile, None] = None):
    tmp_zipfile_path = None
    my_icon = None
    if zipfile:
        tmp_zipfile_path = os.path.join(tempfile.mkdtemp(), zipfile.filename)
        with open(tmp_zipfile_path, "wb+") as file_object:
            shutil.copyfileobj(zipfile.file, file_object)    
    if icon:
        tmp_icon_path = os.path.join(tempfile.mkdtemp(), icon.filename)
        with open(tmp_icon_path, "wb+") as file_object:
            shutil.copyfileobj(icon.file, file_object)  
        try:
            im = Image.open(tmp_icon_path)
            im.verify()
            my_icon = tmp_icon_path
            # do stuff
        except IOError:
            os.remove(tmp_icon_path)
            # filename not an image file
            return error(request, 'Icon file not supported')
    print('create dataset create')
    datasetCreation = models.DatasetCreate(name=name,
                                   folder=folder,
                                   DatabaseID=DatabaseID,
                                   Version=Version,
                                   CopyFolder=CopyFolder=='on',
                                   icon=my_icon)
    print('create dataset')
    dataset = datasetCreation.createDataset(zipfile=tmp_zipfile_path)
    with Session(engine) as session:
        session.add(dataset)
        session.commit()
    print('return dataset')
    return await datasets(request)


@functools.lru_cache(maxsize=12)
def get_ds(folder):
    ds = lazybids.Dataset.from_folder(folder, load_scans_in_memory=False)
    return ds

@app.get("/dataset/{ds_id}", response_class=HTMLResponse)
async def get_dataset(request: Request, ds_id:int):
    if not('hx-request' in request.headers.keys()):
        context = {"request": request,'mainViewURL':f"/dataset/{ds_id}"}
        return templates.TemplateResponse("root.html", context )
    else:
        with Session(engine) as session:
            statement = select(models.Dataset).where(models.Dataset.id==ds_id)
            dataset = session.exec(statement).first()
        try:
            ds = get_ds(dataset.folder)
        except Exception as e:
            return templates.TemplateResponse("components/error.html", context = {"request": request,'error':e} )
        
        return templates.TemplateResponse("components/dataset_view.html", context = {"request": request,'dataset':dataset,'meta_data':ds.all_meta_data} )


@app.get("/dataset/{ds_id}/subjects", response_class=HTMLResponse)
async def get_dataset(request: Request, ds_id:int):
    if not('hx-request' in request.headers.keys()):
        context = {"request": request,'mainViewURL':f"/dataset/{ds_id}"}
        return templates.TemplateResponse("root.html", context )
    else:
        with Session(engine) as session:
            statement = select(models.Dataset).where(models.Dataset.id==ds_id)
            dataset = session.exec(statement).first()
        try:
            ds = get_ds(dataset.folder)
            df = pd.DataFrame([s.all_meta_data for s in ds.subjects])
        except Exception as e:
            return templates.TemplateResponse("components/error.html", context = {"request": request,'error':e} )
        
        context = {'request': request,
                   'columns': df.columns.tolist(),
                   'rows': [{'id':i,'cells':list(p.values())} for i,p in enumerate(df.to_dict('records'))]
                   }
        return templates.TemplateResponse("components/table.html", context = context )
    #df.to_html().replace("class=\"dataframe\"","class='dataframe table table-xs' id='myTable'" )+"<script>let table = new DataTable('#myTable');</script>" #build_table(df, color='blue_light') #templates.TemplateResponse("components/dataset_view.html", context = {"request": request,'dataset':dataset,'meta_data':ds.all_meta_data} )


# @app.get("/search", response_class=HTMLResponse)
# async def root(request: Request, search_text: str):

#     # Initialize beanie with the Product document class
#     my_search = search_text
#     res = search_youtube('Best '+str(my_search)+' 2024')
#     res2 = search_youtube('Best '+str(my_search)+' 2023')
    
#     yts = []
#     for i in res['items']+res2['items']:
#         if i['id']['kind'] == 'youtube#video':
#             yts.append(models.YTVideo(**{'id': i['id']['videoId'],
#                                 'title': html.unescape(i['snippet']['title']),
#                             'channel':i['snippet']['channelTitle'],'my_search':my_search}))
#     context = {"request": request, 'yts': yts}
#     return templates.TemplateResponse("components/yt_carousel.html", context )

# @app.get("/yt_products/{yt_id}/{my_search}", response_class=HTMLResponse)
# async def yt_products(request: Request, yt_id:str, my_search:str='Cordless vacuum'):
#     try:
#         transcript = YouTubeTranscriptApi.get_transcript( yt_id)
#     except:
#         return templates.TemplateResponse("components/products_empty.html", {"request": request} )
#     task = get_productList_from_transcript.delay(transcript, my_search)  
#     print(f'Spawned process for {task.id}')
#     return templates.TemplateResponse("components/products_delayed.html", {"request": request, 'mytask':{"id":str(task.id)},'delay':500})

# @app.get("/yt_products_status/{task_id}", response_class=HTMLResponse)
# async def yt_products_status(request: Request, task_id:str):
#     print(f'got status request for {task_id}')
#     task = get_productList_from_transcript.AsyncResult(task_id)
#     if task.state == 'FAILURE':
#         return templates.TemplateResponse("components/products_empty.html", {"request": request} )
#     elif task.state == 'PENDING':
        
#         return templates.TemplateResponse("components/products_delayed.html", {"request": request, 'mytask':{"id":str(task_id)},'delay':2500} )
#     elif task.state == 'SUCCESS':
#         if not(task.result):
#             return templates.TemplateResponse("components/products_empty.html", {"request": request} )
#         products = models.ProductsList(products=task.result[1]['products'], transcript=str(task.result[0]))
#         context = {"request": request, 'products': products}
#         return templates.TemplateResponse("components/products.html", context )
#     else:
#         return templates.TemplateResponse("components/products_delayed.html", {"request": request,'mytask':{"id":str(task_id)},'delay':2500}  )