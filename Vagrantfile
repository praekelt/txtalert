Vagrant::Config.run do |config|
  
  config.vm.box = "lucid32"
  config.vm.box_url = "http://files.vagrantup.com/lucid32.box"
  
  config.vm.provision :puppet do |puppet|
    # puppet.options = "--verbose --debug"
    puppet.module_path = "puppet/modules"
    puppet.manifests_path = "puppet/manifests"
    puppet.manifest_file = "txtalert.pp"
  end
  
  config.vm.forward_port "web", 80, 4567
  config.vm.forward_port "supervisord", 7010, 7010
end
