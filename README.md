# Multi-Robot Rendezvous
## Data Collection

### step1: Collect google map street view url
Before data processing, you should prepare a `url.txt` under the `googledata/seed{YOUR_DATA_SEED}/`.

Here is an example: [url.txt](docs/resources/url.txt)

You can enter arbitrary position street view by google map like ![streetview_example.png](docs/resources/streetview_example.png)

Then in the streetview mode, you can go through a route like an agent. Each step you move, copy the url into `url.txt` in order. 

![streetview_move_example.png](docs/resources/streetview_move_example.png)

There is a `X` symbol on the ground to label where the next step is, do not move one step too far away. 

### step2: Use script to process the view url
```shell
python googledataprocess.py --api-key YOUR_API_KEY --seed YOUR_DATA_SEED
```

This command will create a `route.html`, `route_only_end.html` and some streetview images under the `googledata/seed{YOUR_DATA_SEED}/`.

```
└── googledata
    ├── seed0
        ├── url.txt
        ├── pano.json
        ├── route.html
        ├── route_only_end.html
        ├── streetview_{Agent}_{Time_index}_{Camera_label}.png
    ├── seed1
    ├── ...
```

The `route.html` will be like this after rendered by browser
![route.png](docs/resources/route.png)

The `route_only_end.html` will be like after rendered by browser
![route_only_end.png](docs/resources/route_only_end.png)