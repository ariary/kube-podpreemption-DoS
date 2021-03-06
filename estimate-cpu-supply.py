import argparse
import sys
import time

from kubernetes import client, config

DEPLOYMENT_NAME = "deployment-estimate"
IMAGE="nginxdemos/hello"


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def create_deployment_object(cpu,start):
    # Configureate Pod template container
    container = client.V1Container(
        name="estimate",
        image=IMAGE,
        image_pull_policy="IfNotPresent",
        resources=client.V1ResourceRequirements(
            requests={"cpu": cpu, "memory": "128Mi"},
            limits={"cpu": cpu, "memory": "128Mi"},
        ),
    )

    # Create and configure a spec section
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": "estimate"}),
        spec=client.V1PodSpec(containers=[container]),
    )

    # Create the specification of deployment
    spec = client.V1DeploymentSpec(
        replicas=start, template=template, selector={
            "matchLabels":
            {"app": "estimate"}})

    # Instantiate the deployment object
    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(name=DEPLOYMENT_NAME),
        spec=spec,
    )

    return deployment


def create_deployment(api, deployment,namespace,start):
    # Create deployement
    resp = api.create_namespaced_deployment(
        body=deployment, namespace=namespace
    )

    eprint("[INFO] deployment created with %s replicas" % str(start))


def scale_deployment(api, deployment,new_replicas,namespace):
    # Update deployment replicas
    deployment.spec.replicas = new_replicas
    # patch the deployment
    resp = api.patch_namespaced_deployment(
        name=DEPLOYMENT_NAME, namespace=namespace, body=deployment
    )


def delete_deployment(api,namespace):
    # Delete deployment
    resp = api.delete_namespaced_deployment(
        name=DEPLOYMENT_NAME,
        namespace=namespace,
        body=client.V1DeleteOptions(
            propagation_policy="Foreground", grace_period_seconds=5
        ),
    )
    eprint("[INFO] deployment deleted.")

def autostuff(api, deployment,namespace,start,increment,timeout):
    """
    Loop: Scale the deployment adding [INCREMENT] to replicas, restart it and see if all the pod are successfully running
    if one pod is pending => exit and return the number of replica to trigger out-of-resource event
    Otherwise it loops again
    """
    nreplicas = start
    while(True):
        # get current replicas statuses
        time.sleep(timeout)
        pending = not all_running_pod(namespace,timeout)
        if pending:
            break
        # Add replicas
        nreplicas += increment
        scale_deployment(api,deployment,nreplicas,namespace)
        eprint("[INFO] Scale deployment replicas: " + str(nreplicas))

    return nreplicas
        


def all_running_pod(namespace,timeout):
    """
    Return true if all pods of the deployment are running.
    Conversely return false if one pod is pending
    """
    pod_list = client.CoreV1Api().list_namespaced_pod(namespace,label_selector='app=estimate')
    for pod in pod_list.items:
        if pod.status.phase != "Running":
            eprint("[INFO] Not running Pod %s: {Status: %s}" % (pod.metadata.name,pod.status.phase))
            #container status: %s ....pod.status.container_statuses[0].state.waiting.reason)
            # Check outofCpu event
            if pod.status.conditions:
                msg = pod.status.conditions[0].message
                if "Insufficient cpu" in msg:
                    return False
            elif pod.status.container_statuses: #Check if container is successfully created => if not wait and re-check Running status
                if pod.status.container_statuses[0].state.waiting.reason == "ContainerCreating":
                    eprint("[INFO] Pod is pending due to ContainerCreating state, wait again")
                    time.sleep(timeout)
                    all_running_pod(namespace,timeout)
            else:
                eprint("[WARNING] Check that the pod that isn't running is pending due to a Out-of-resource event")
                return False
    return True

def estimate(args):
    config.load_kube_config()
    apps_v1 = client.AppsV1Api()

    deployment = create_deployment_object(args.cpu,args.replicas)

    create_deployment(apps_v1, deployment,args.namespace,args.replicas)

    replicas = autostuff(apps_v1, deployment,args.namespace,args.replicas,args.increment,args.timeout) - args.increment #replica number to stuff cluster

    print(str(replicas))
    if not args.no_deletion:
        delete_deployment(apps_v1,args.namespace)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Estimate cpu to allocate to stuff nodes and generate Out-Of-Cpu event.')
    parser.add_argument('-n','--namespace',type=str,default="bad-tenant", help='namespace for the deployment')
    parser.add_argument('-r','--replicas',type=int,default=1,help='initial number of replica pods (must be > 0)')
    parser.add_argument('-i','--increment',type=int,default=1,help='increment replica number by this value at each step')
    parser.add_argument('--cpu',type=str,default="1",help='cpu requests/limits of each pods of the deployment')
    parser.add_argument('-t','--timeout',type=int,default=7,help='timeout to wait before asking Pod statuses at each step')
    parser.add_argument("-k","--no-deletion", help="disable deployment deletion when the script exits",action='store_true')

    args = parser.parse_args()
    estimate(args)
