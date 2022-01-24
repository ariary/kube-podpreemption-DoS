

# K8s - Pod Denial-of-Service using Pod Priority preemption



[TOC]

The aim is to demonstate how we could perform the Denial-of-Service on another pod in the same kubernetes cluster using `PodPriority`. By DoS we mean:

* Pod eviction, if the target pod is already running
* Block pod rescheduling

It is mainly harmful in a multi-tenant cluster. A tenant can use this mechanism to perform a DoS on other tenant applications or even on "administration" pods

## 🧾Resource Quota

When several users or teams share a cluster with a fixed number of nodes, there is a concern that one team could use more than its fair share of resources ***~>*** **Resource Quotas**: limit aggregate resource consumption per namespace: quantity of objects + compute resources that may be consumed

| Property                                                     |
| ------------------------------------------------------------ |
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
| ------------------------------------------------------------ |
| If quota is enabled in a  namespace for compute resources like cpu and memory, users must specify  requests or limits for those values |

**Request *vs* Limit:**  A request is the amount of resource garuanteed by Kubernetes for the container. Conversaly, a limit for a resource is the maximum amount of a resource that Kubernetes will allow to the container use

### Recommanded use

* 1 ns per team
* Admin creates 1 ResourQuota for each ns
* Users create resources (pods, services, etc.) in the namespace, and the quota system tracks usage to ensure it does not exceed hard resource limits defined in a ResourceQuota.

## 🛑 Pod Priority and Preemption

**Pod priority**: If a Pod cannot be scheduled, the scheduler tries to preempt (evict) lower priority Pods to make scheduling of the pending Pod possible.

When a pod with priority is in pending mode, the scheduler searches node with lower priority pod and if the eviciton of this pod make the higher priority pod scheduling possible  ⇒ Lower pod evicted + higher pod scheduled. 

### How to use `PodPriority`?

1. Add one or more [PriorityClasses](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#priorityclass).
2. Create Pods with[`priorityClassName`](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#pod-priority) 

That's all! Note that all previous created pods are set with the default Priority (which is `0`)

### Test eviction and schedule blocking

| Property                                                     |
| :----------------------------------------------------------- |
| It supports **eviction decisions based on incompressible resources**.<br />Eviction doesn’t happen if pressure is on compressible resources, e.g., CPU. fake |

**Notes:** This property only apply to kubelet eviction. CPU resource can indeeend be used to perform Out-Of-Resource cluster state and thus launching eviction process for higher pod creation.

| Property                                                     |
| :----------------------------------------------------------- |
| **In the case of memory pressure: **<br />* Pods are sorted first based on whether  their memory usage exceeds their request or not, then by pod priority,  and then by consumption of memory relative to memory requests<br />* Pods that don’t exceed memory requests are not evicted. A lower priority pod that doesn’t exceed memory requests will not be evicted |

***(❓) Could we evict already running pod by creating pod with higher priority ?***

> Yes !  [see](https://kubernetes.io/docs/concepts/scheduling-eviction/_print/#preemption)

***(❓) Could we block pod scheduling by running higher priority pod ?***

> Yes ! With the same mechanism. If we have a running higher-priority pod that is just under a  specific resource limit use that would exhaust the resource supply, all lower-priority pods won't be scheduled till the resource supply is not sufficient [see](https://kubernetes.io/docs/concepts/scheduling-eviction/_print/#effect-of-pod-priority-on-scheduling-order) 

***(❓) Is this attack is inter-namespace feasable ?***

> Yes !

***(❓) To trigger Out-of-Resource state, we need to exhaust the resource supply of the cluster ?***

> No, we need to exhaust the supply of a specific node ([see](https://kubernetes.io/docs/tasks/configure-pod-container/assign-cpu-resource/#specify-a-cpu-request-that-is-too-big-for-your-nodes)), **BUT** if the cluster resource supply isn't exhausted and you don't specify the node you want to exhaust, the malicious Pod will be scheduled on a node with adequat supply w/o evicting any pod.



## 🔫 PoC

To preempt pod you must have 1 pod pending with higher priority that already scheduled pods. We will put our cluster in **Out-Of-Resource state using `cpu`oversupply**

Use your cluster or create one with 4 nodes and cpu limit at `4`:

```shell
minikube start --cpus 4 --nodes 4
```

  In fact, `--cpus 2`seems to be useless. It is the value of capacity.cpu find with `kubectl get nodes -o=jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.capacity.cpu}{"\n"}{end}'` that has importance (here `4`)

1. Create low-priority pods or pods without priorityClass ( ⇒ priority `0`).

   With a daemonSet to be sure to have one on each node:

   ```yaml
   apiVersion: apps/v1
   kind: DaemonSet
   metadata:
     name: ds-no-priority
   spec:
     selector:
       matchLabels:
         run: ds-no-priority
     template:
       metadata:
         labels:
           run: ds-no-priority
       spec:
         containers:
           - name: somecontainer
             image: nginxdemos/hello
             resources:
               requests:
                 cpu: 1
                 memory: "128Mi"
               limits:
                 cpu: 1
                 memory: "128Mi"
   ```

   Make this thrice (change ds name and so on). 

   At this point, you must have 12 pods running, 3 on each nodes. Each nodes uses ~3 cpu.

2. Create pod with high priority. The key is it musts have `cpu` requests & limits so that:

   * Total cpu requested of all pods is greater than the total amount of cpu available for each nodes ⇒ exhaust the supply of CPU
   * cpu request is not greater than maximum node cpu ⇒ Making the pod scheduling possible (if lower-priority pod is evicted)

   pod-high.yml:

   ```yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: high-priority
   spec:
     containers:
     - name: high-priority
       image: nginxdemos/hello
       resources:
         requests:
           cpu: 1
           memory: 128Mi
         limits:
           cpu: 1
           memory: 128Mi
   ```

   

   See that this will evict a low-priority pod (`Pending` status) and start `high-priority`pod.

   

### Evict a specific Pod

(see [limits](#limits) to have more details)

***How we can proceed?***

* Deploy malicious pod with inter-pod affinity if you know the target pod label values.
  * In a more sophisticated attack, you could use anti-affinity to deploy higher-prority pods on all nodes where the target pods isn't deployed (to block future rescheduling). Then, evict target pods using node affinity / pod anti afinity to deploy malicious pod
* Deploy  the malicious pod on the same node than the target pod , if you already know on which node the target pod is running



## Limits

* If you reach the `ResourceQuota` you could not create the malicious pod (it won't be place in pending mode, so not in scheduling queue). So  the attack is not doable.
* In the case of memory pressure, **pods are sorted first based on whether  their memory usage exceeds their request or not**, then by pod priority,  and then by consumption of memory relative to memory requests
* If you want to deploy a deployment of malicious  pods. If all the pods can't be scheduled, an `OutofCpu` status is set and no lower-priority pods are evicted.
* You can't specify a `pod.spec.nodeName` in your malicious pod to evict pod of a specific node. It will be scheduled on node with status `OutOfcpu`. (It seems that it Doesn't pass by the kubelet scheduler  so it won't evict lower-priority pods)
  * use of  `pod.spec.nodeSelector` performs lower-priority pods eviction
  * use of  `pod.spec.affinity.nodeAffinity` performs lower-priority pods eviction
  * use of `pod.spec.affinity.podAffinity` does not perform pods evicition. Malicious pod is pending.
  * use of  `pod.spec.affinity.podAntiAffinity` performs lower-priority pods eviction. (Condition: cpu supply close to be exhausted and match target pod labels with `antiPodAffinity` and `preferredDuringSchedulingIgnoredDuringExecution` + no other pod must have this label. Curiously it will schedule the malicious pod on the same node as the pod specified by antiAffinity)




## 🛡 Protection & Mitigation

* Put `ResourceQuota` on each namespaces to limit resource use. Check that the addition of the wholes limits & requests within aren't higher than the overall of the cluster resources
  * In addition, enforce specification of pod resources
  * launch an alert based on limit and requests (if no limit are supplied in resourcequota, resource requests is too big, etc...)
* Allow `ResourceQuota`, `PodPriority` use only for admin users (generally the same for all cluster wide resources)
* Add rules via admission controller to prevent specific use of higher PriorityClasses (e.g. disallow `system-node-critical` for non-admin ns)
* Create Non-preempting PriorityClass (with `preemptionPolicy: Never`) to block preemption by higher priority pods ***~>*** higher-priority pods are placed in the scheduling queue ahead of lower-priority pods, but they cannot preempt other pods. This comes w/ a downside: pods with lower priority could be scheduled before them ([see](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#non-preempting-priority-class))



## 📖 Cheat Sheet

* Get clusters resources available: `kubectl top nodes` *(need  the right to list resource "nodes" in API group "metrics.k8s.io" at the cluster scope + metric-server deployed)*
  * enable metric-server w/ minikube: `minikube addons enable metrics-server`
  * otherwise use `kubectl get nodes -o=jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.capacity.cpu}{"\n"}{end}'`
* Get pod priority classes: `kubectl get PriorityClass`
* `cpu`usage
  * stats on container cpu usage (%): `docker stats [container_name]`
  * docker cpu limit: (in container) `cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us`divided by `cat /sys/fs/cgroup/cpu/cpu.cfs_period_us` give us the limit number of cpu alloxated for the container
  * `kubectl describe nodes [node_name]`
  * watch pod changement in namespace: `watch -d -n 0.1 kubectl get pods -o wide`

## 👀Additional Resources

- [Resource Quota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
- [Pod priority preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/#pod-priority)

* https://kubernetes.io/docs/concepts/scheduling-eviction/_print/#pods-are-preempted-but-the-preemptor-is-not-scheduled
* https://docs.openshift.com/container-platform/4.7/nodes/pods/nodes-pods-priority.html
* https://blog.wescale.fr/2019/01/29/k8s-preemption-et-priorites-de-pods/
* ~~https://dzone.com/articles/please-dont-evict-my-pod-priority-amp-disruption-b~~
  * https://grafana.com/blog/2019/07/24/how-a-production-outage-was-caused-using-kubernetes-pod-priorities/
* https://medium.com/container-talks/ultimate-guide-of-pod-eviction-on-kubernetes-588d7f6de8dd
* https://github.com/rajatjindal/kubectl-evict-pod



## 🖋TO DO

- [x] All affinity
- [ ] Pod qui détermine cpu limit à ecrire
- [ ] Malicious pod qui target un pod spécifique
- [ ] Check: 1 master no deployment, PoC on worker Pour bien vérifié que c'est bien les ressource d'un noeud pas du cluster
