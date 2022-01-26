import argparse
import sys
import time

from kubernetes import client, config

DEPLOYMENT_NAME = "deployment-stuffer"
POD_NAME = "evictor"
IMAGE="nginxdemos/hello"


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def create_high_priority_deployment_object(cpu,nreplicas,priority):
    # Configureate Pod template container
    container = client.V1Container(
        name="stuffer",
        image=IMAGE,
        image_pull_policy="IfNotPresent",
        resources=client.V1ResourceRequirements(
            requests={"cpu": cpu, "memory": "128Mi"},
            limits={"cpu": cpu, "memory": "128Mi"},
        ),
    )

    # Create and configure a spec section
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": "stuffer"}),
        spec=client.V1PodSpec(containers=[container],priority_class_name=priority),
        
    )

    # Create the specification of deployment
    spec = client.V1DeploymentSpec(
        replicas=nreplicas, template=template, selector={
            "matchLabels":
            {"app": "stuffer"}})

    # Instantiate the deployment object
    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(name=DEPLOYMENT_NAME),
        spec=spec,
    )

    return deployment


def create_high_priority_deployment(api, deployment,namespace,start):
    # Create deployement
    resp = api.create_namespaced_deployment(
        body=deployment, namespace=namespace
    )

    eprint("[INFO] deployment created with %s replicas" % str(start))

def create_evictor_pod_object(cpu,priority):
    # Configurate container
    container = client.V1Container(
        name="evictor",
        image=IMAGE,
        image_pull_policy="IfNotPresent",
        resources=client.V1ResourceRequirements(
            requests={"cpu": cpu, "memory": "128Mi"},
            limits={"cpu": cpu, "memory": "128Mi"},
        ),
    )

    # Pod metadata
    metadata = client.V1ObjectMeta(name=POD_NAME)
    # Pod spec
    spec = client.V1PodSpec(
        containers=[container],
        priority_class_name=priority,
    )

    # Instantiate the Pod object
    evictor_pod = client.V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=metadata,
        spec=spec,
    )

    return evictor_pod


def create_evictor_pod(api, pod,namespace):
    # Create pod
    resp = api.create_namespaced_pod(
        body=pod, namespace=namespace
    )

    eprint("[INFO] evictor pod is created")

    def clean_helper(namespace):
    eprint("[INFO] To delete deployment: kubectl -n %s delete deployment %s" % (namespace,DEPLOYMENT_NAME))
    eprint("[INFO] To delete evictor pod: kubectl -n %s delete pod %s" % (namespace,POD_NAME))

def evict(args):
    config.load_kube_config()
    apps_v1 = client.AppsV1Api()
    core_v1 = client.CoreV1Api()

    deployment = create_high_priority_deployment_object(args.cpu,args.replicas,args.priority)

    create_high_priority_deployment(apps_v1, deployment,args.namespace,args.replicas)

    time.sleep(args.timeout)

    evictor_pod = create_evictor_pod_object(args.cpu,args.priority)

    create_evictor_pod(core_v1, evictor_pod,args.namespace)
    
    clean_helper(args.namespace)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Stuff cluster with a deployment. Then create pod that will evict other pods ("evictor-pod")')
    parser.add_argument('-n','--namespace',type=str,default="bad-tenant", help='namespace used for eviction')
    parser.add_argument('-r','--replicas',type=int,default=1,help='initial number of replica pods (must be > 0)')
    parser.add_argument('--cpu',type=str,default="1",help='cpu requests/limits of each pods created')
    parser.add_argument('-p','--priority',type=str,default="high-priority",help='specify priorityClass name of pods')
    parser.add_argument('-t','--timeout',type=int,default=7,help='timeout between deployment creation and evictor-pod creation')

    args = parser.parse_args()
    evict(args)
